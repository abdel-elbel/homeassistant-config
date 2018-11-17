"""
Support for the Bouygues Telecom SMS platform.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/notify.bouygues/
"""
import logging
import requests
import re
import voluptuous as vol

from homeassistant.components.notify import (
    PLATFORM_SCHEMA, BaseNotificationService)
from homeassistant.const import (CONF_PROFILE_NAME, CONF_USERNAME, CONF_PASSWORD, 
CONF_RECIPIENT)
import homeassistant.helpers.config_validation as cv

DOMAIN = "notify"
LOGIN_URL = 'https://www.mon-compte.bouyguestelecom.fr/cas/login'
API_URL = 'https://www.secure.bbox.bouyguestelecom.fr/services/SMSIHD'

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_PROFILE_NAME): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_RECIPIENT, default=[]):
            vol.All(cv.ensure_list, [cv.string]),
})


def get_service(hass, config, discovery_info=None):
    """Get the Bouygues Telecom Mobile SMS notification service."""
    return BouyguesSMSNotificationService(config)


class BouyguesSMSNotificationService(BaseNotificationService):
    """Implement a notification service for the Bouygues Telecom Mobile SMS service."""

    def __init__(self, config):
        """Initialize the service."""
        lastname = config[CONF_PROFILE_NAME]
        username = config[CONF_USERNAME]
        password = config[CONF_PASSWORD]
        self.numbers = config[CONF_RECIPIENT]
        self.client = BouyguesClient(lastname, username, password)

    def send_message(self, message="", **kwargs):
        """Send a message to the Bouygues Telecom Mobile user cell."""
        resp = self.client.send(message, self.numbers)

        if resp == "LOGIN_UNKNOWN":
            _LOGGER.error("Login Unknown")
        elif resp == "LOGIN_WRONG":
            _LOGGER.error("Wrong Username/Password")
        elif resp == "QUOTA_EXCEEDED" :
            _LOGGER.error("Too much SMS send in a few time")
        elif resp == "ERROR_GETQUOTA":
            _LOGGER.error("Error getting quota")
        elif resp == "ERROR_GETSENDERNUMBER":
            _LOGGER.error("Error getting sender number")
        elif resp == "CODE_ERROR_1003":
            _LOGGER.error("Technical problem encountered at SMS page")


class BouyguesClient(object):
    """
    The Bouygues Telecom Mobile client uses 4 URLs :
    # login : https://www.mon-compte.bouyguestelecom.fr/cas/login
    # step 1 : https://www.secure.bbox.bouyguestelecom.fr/services/SMSIHD/sendSMS.phtml
    # step 2 : https://www.secure.bbox.bouyguestelecom.fr/services/SMSIHD/confirmSendSMS.phtml
    # step 3 : https://www.secure.bbox.bouyguestelecom.fr/services/SMSIHD/resultSendSMS.phtml
    """
        
    def __init__(self, lastname, user, passwd):
        """
        Create a new Bouygues Telecom Mobile client.
        """
        self._lastname = lastname
        self._user = user
        self._passwd = passwd
        _LOGGER.info('Profile created')
        
    def login(self):
        from requests.utils import quote
        """
        Login to the Bouygues Telecom site using the credentials through :
        1 - Authenticate + Get sessionId & lt
        2 - Login to base URL using sessionId & lt
        3 - Access to base URL and retrieve info
        """
        BASE_URL_1 = "{}/sendSMS.phtml".format(API_URL)
        
    #==========================================================================
    #  PART 1 - Authenticate + Get sessionId & lt
    #==========================================================================

        lastname = self._lastname 
        username = self._user
        password = self._passwd
        code = ''
         
        _LOGGER.info("Authenticating..")
        sess = requests.Session()
        response = sess.get(LOGIN_URL) 
    
        jsessionid = re.search(b'JSESSIONID=(.*); Path=\/cas\/; HttpOnly'.decode('utf-8'),  response.headers["set-cookie"])
        lt = re.search('<input type=\"hidden\" name=\"lt\" value=\"([a-zA-Z0-9_-]*)\"', response.content.decode('utf-8'))
        
        if (jsessionid == None) | (lt == None):
            code = "LOGIN_UNKNOWN"
            return code
        else:
            jsessionid = jsessionid.groups()[0] 
            lt = lt.groups()[0]
            _LOGGER.info("Got jsessionid " + jsessionid);
            _LOGGER.info("Got lt value " + lt);
    
    #==========================================================================
    #  PART 2 - Login to base URL using sessionId & lt
    #==========================================================================
    
        postData = {
                  'lastname': lastname,  
                  'username': username,
                  'password': password,
                  'rememberMe': 'true',
                  '_rememberMe': 'on',
                  'lt': lt,
                  'execution': 'e1s1',
                  '_eventId': 'submit'
                  }
        
        BASE_URL_1_encoded = quote(BASE_URL_1, safe='')
        url = LOGIN_URL + ";jsessionid=" + jsessionid + "?service=" + BASE_URL_1_encoded
        response = sess.post(url, data = postData)       
        err = re.search('<p class=\"color-mid-grey\">Votre identifiant ou votre mot de passe est incorrect<\/p>', response.content.decode('utf-8'))
        
        if err != None :
            code = "LOGIN_WRONG"
            return code
        else :
            _LOGGER.info("Authenticated successfully!")
            self._session = sess
            
    #==========================================================================
    #  PART 3 - Access to base URL and retrieve info
    #==========================================================================
            
        response = sess.get(BASE_URL_1)  
        
        #quota
        quota = re.search(b'Il vous reste <strong>(\d*) SMS gratuit\(s\)<\/strong>', response.content)

        if quota == None :
            code = "ERROR_GETQUOTA"
            return code
        else :
            quota = quota.groups()[0].decode("utf-8") 
            _LOGGER.info(quota + "/5 message(s) left")
            
        if int(quota) == 0:
            code = "QUOTA_EXCEEDED"
            return code
                
        self.quota = int(quota)
        
        #sender
        sender = re.search(b'<span class="txt11">Votre SMS apparaitra comme provenant du : (.*)</span>', response.content)
    
        if sender == None :
            code = "ERROR_GETSENDERNUMBER"
            return code
        else :
            sender = sender.groups()[0].decode("utf-8") 
            _LOGGER.info(sender + " is the sender's number")
            sender = sender.replace(" ", "")
            
        self.sender = sender
                
        return code
  
    def send(self, msg, numbers=[]):
        err = self.login()
        maxLength = 160
        sep = ';'
        
        if err :
            _LOGGER.error('Message not sent due to login error : %s' % err)
        else :
            quota = self.quota
            
            if numbers:
                if isinstance(numbers, list):
                    numbers = list(set(numbers))
                    if len(numbers) > int(quota):
                        _LOGGER.warning('WARNING : too many numbers to send to. Only the %s first numbers will be used' % quota)
                        numbers = numbers[0:(quota-len(numbers))]
                        
                    numbers = sep.join(numbers)
            else:
                numbers = self.sender
            
            if len(msg) > maxLength : 
                _LOGGER.warning('WARNING : message have been cut to %s characters to respect the max length ' % maxLength)
                msg = str(msg)[0:maxLength]
            
            return self.sendSMS(msg, numbers)

            
    def sendSMS(self, msg, numbers):
        _LOGGER.info("Sending %s to %s.." % (msg, numbers))
        sess = self._session
        code = ''
        BASE_URL_1 = "{}/sendSMS.phtml".format(API_URL)
        BASE_URL_2 = "{}/confirmSendSMS.phtml".format(API_URL)
        BASE_URL_3 = "{}/resultSendSMS.phtml".format(API_URL)
        
        
    #==========================================================================
    #  Step 1 : 'envoyer un sms', 'valider'
    #==========================================================================
        
        postdata = {
                    'fieldMsisdn': numbers,
                    'fieldMessage': msg,
                    'Verif.x': '72',
                    'Verif.y': '17'
                    }
        
        
        step1 = sess.post(BASE_URL_2, postdata)  
        
        err = re.search('Suite \xc3\xa0 un probl\xc3\xa8me technique, nous ne sommes pas en mesure de r\xc3\xa9pondre \xc3\xa0 votre demande.', step1.content.decode("utf-8"))        
        if err != None :
            code = "CODE_ERROR_1003 : Technical problem encountered"
            return code
        else:
            verify = re.search('<span class=\"titre\" style=\"float:left;\">Validation<\/span>', step1.content.decode("utf-8"))
            if verify != None :
                
    #==========================================================================
    #  Step 2 : 'validation', 'envoyer'
    #==========================================================================
    
                _LOGGER.info("SMS Confirmation page..")
                
                postdata = {
                            'msisdn': numbers,
                            'msg': msg,
                            'Verif.x': '79',
                            'Verif.y': '17'
                            }
                BASE_URL_1 = "{}/sendSMS.phtml".format(API_URL)
                step2 = sess.post(BASE_URL_1, postdata) 
                
    #==========================================================================
    #  Step 3 : 'result', 'envoyer'
    #==========================================================================
                
                step3 = sess.get(BASE_URL_3)  
                verify = re.search('Votre message a bien été envoyé au numéro', 
                                   step3.content.decode("utf-8"))
                if verify != None :
                    _LOGGER.info("SMS Sent !")
                
        sess.close()
        return code