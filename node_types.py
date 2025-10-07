""" Node classes used by the Hue Node Server. """

import json
import udi_interface
from converters import RGB_2_xy, color_xy, kel2mired

LOGGER = udi_interface.LOGGER

# Hue Default transition time is 400ms
DEF_TRANSTIME = 400
# Increment for DIM and BRT commands
DEF_INCREMENT = 10
# Transition time for FadeUp/Down commands
FADE_TRANSTIME = 4000

HUE_EFFECTS = ['none', 'colorloop']
HUE_ALERTS = ['none', 'select', 'lselect']

class HueBase(udi_interface.Node):
    """ Base class for lights and groups """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx):
        super().__init__(polyglot, primary, address, name)
        self.controller = self.poly.getNode(self.primary)
        self.name = name
        self.address = address
        self.element_id = element_id
        self.data = element
        self.on = None
        self.st = None
        self.brightness = None
        self.saved_brightness = None
        self.alert = None
        self.transitiontime = DEF_TRANSTIME
        self.ct = None
        self.hue = None
        self.saturation = None
        self.color_x = None
        self.color_y = None
        self.effect = None
        self.hub_idx = hub_idx
        self.zigbee_connectivity_id = None
        self.parent_device_id = None
        self.reachable = 0

    def query(self):
        pass

    def setBaseCtl(self, command):
        """ Basic On/Off and brightness controls """
        cmd = command.get('cmd')

        # transition time for FastOn/Off
        if cmd in [ 'DFON', 'DFOF' ]:
            trans = 0
        else:
            trans = self.transitiontime

        if cmd in ['DON', 'DFON']:
            hue_command = {}
            val = command.get('value')
            if val:
                self.brightness = self._validateBri(int(val))
                hue_command = {'dimming': {'brightness': self.brightness } }
                self.setDriver('GV5', self.brightness)
            elif cmd == 'DON' and self.on and self.controller.ignore_second_on:
                # Ignore DON command if bulb is On already
                LOGGER.info(f'Ignoring On command, {self.name} is already On')
            elif cmd == 'DFON' or self.on:
                # Go to full brightness on Fast On or if already On
                self.brightness = 100
                hue_command = {'dimming': {'brightness': self.brightness } }
                self.setDriver('GV5', self.brightness)
            self.st = self.brightness
            # setting self.on to False to ensure that _send_command will add it
            self.on = False
            # if this is a Hue Group class
            #if hasattr(self,'all_on'):
            #    self.all_on = False
            self._send_command(hue_command, trans)
        elif cmd in ['DOF', 'DFOF']:
            self.on = False
            #if hasattr(self,'all_on'):
            #    self.all_on = False
            self.st = 0
            hue_command = { 'on': { 'on': self.on } }
            self._send_command(hue_command, trans, False)
            if trans != DEF_TRANSTIME:
                # Work around a known bug in Hue - setting the light off with transition time
                # resets brightness to a random level, we'll attempt to re-set it here
                self.saved_brightness = self.brightness
        elif cmd in ['BRT', 'DIM', 'FDUP', 'FDDOWN', 'FDSTOP']:
            if cmd == 'BRT':
                increment = DEF_INCREMENT
                if self.brightness + increment > 100:
                    increment = 100 - self.brightness
            elif cmd == 'DIM':
                increment = -DEF_INCREMENT
                if self.brightness + increment < 1:
                    increment = 1 - self.brightness
            elif cmd == 'FDUP':
                trans = FADE_TRANSTIME
                increment = 100 - self.brightness
            elif cmd == 'FDDOWN':
                trans = FADE_TRANSTIME
                increment = 1 - self.brightness
            else:
                # FDSTOP
                increment = 0
            self.brightness += increment
            self.st = self.brightness
            hue_command = { 'bri_inc': increment }
            self.setDriver('GV5', self.brightness)
            self._send_command(hue_command, trans)
        else:
            LOGGER.error(f'setBaseCtl received an unknown command: {cmd}')
        self.setDriver('ST', self.st)

    def setBrightness(self, command):
        self.brightness = self._validateBri(int(command.get('value')))
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        hue_command = { 'dimming': {'brightness': self.brightness }}
        return self._send_command(hue_command)

    def setTransition(self, command):
        self.transitiontime = int(command.get('value'))
        self.setDriver('RR', self.transitiontime)
        return True

    def setAlert(self, command):
        val = int(command.get('value')) - 1
        self.alert = HUE_ALERTS[val]
        hue_command = { 'alert': self.alert }
        return self._send_command(hue_command)

    def _validateBri(self, brightness):
        if brightness > 100:
            brightness = 100
        elif brightness < 0:
            brightness = 0
        self.st = brightness
        return brightness

    def setCt(self, command):
        self.ct = int(command.get('value'))
        self.setDriver('CLITEMP', self.ct)
        hue_command = {'color_temperature': { 'mirek': kel2mired(self.ct) }}
        return self._send_command(hue_command)

    def setCtBri(self, command):
        query = command.get('query')
        self.brightness = self._validateBri(int(query.get('BR.uom100')))
        self.ct = int(query.get('K.uom26'))
        self.setDriver('CLITEMP', self.ct)
        self.setDriver('ST', self.st)
        self.setDriver('GV5', self.brightness)
        hue_command = { 'color_temperature': {'mirek': kel2mired(self.ct)}, 'dimming': {'brightness': self.brightness }}
        return self._send_command(hue_command)

    def setColorRGB(self, command):
        query = command.get('query')
        color_r = int(query.get('R.uom100'))
        color_g = int(query.get('G.uom100'))
        color_b = int(query.get('B.uom100'))
        transtime = int(query.get('D.uom42'))
        self.brightness = self._validateBri(int(query.get('BR.uom100')))
        (self.color_x, self.color_y) = RGB_2_xy(color_r, color_g, color_b)
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}, 'dimming': {'brightness': self.brightness}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        return self._send_command(hue_command, transtime)

    def setColorXY(self, command):
        query = command.get('query')
        self.color_x = float(query.get('X.uom56'))
        self.color_y = float(query.get('Y.uom56'))
        transtime = int(query.get('D.uom42'))
        self.brightness = self._validateBri(int(query.get('BR.uom100')))
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}, 'dimming': {'brightness': self.brightness}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        return self._send_command(hue_command, transtime)

    def setColor(self, command):
        c_id = int(command.get('value')) - 1
        (self.color_x, self.color_y) = color_xy(c_id)
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        return self._send_command(hue_command)

    def setEffect(self, command):
        val = int(command.get('value')) - 1
        self.effect = HUE_EFFECTS[val]
        hue_command = { 'effect': self.effect }
        return self._send_command(hue_command)

    def process_event(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if 'on' in event:
            if event['on']['on']:
                self.reportCmd('DON')
                self.st = self.brightness
            else:
                self.reportCmd('DOF')
            self.on = event['on']['on']
        if 'dimming' in event:
            self.brightness = event['dimming']['brightness']
            self.st = event['dimming']['brightness']
            self.setDriver('GV5', self.brightness)
        if self.on:
            self.setDriver('ST', self.st)
        else:
            self.setDriver('ST', 0)
        if 'color' in event:
            self.color_x = round(float(event['color']['xy']['x']), 4)
            self.color_y = round(float(event['color']['xy']['y']), 4)
            self.setDriver('GV1', self.color_x)
            self.setDriver('GV2', self.color_y)
        if 'color_temperature' in event:
            if event['color_temperature']['mirek_valid']:
                self.ct = kel2mired(event['color_temperature']['mirek'])
                self.setDriver('CLITEMP', self.ct)

    def process_connectivity(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if event['status'] == 'connected':
            self.reachable = 1
        else:
            self.reachable = 0
        self.setDriver('GV6', self.reachable)
    def _send_command(self, command, transtime=None, checkOn=True):
        pass

    drivers = []
    commands = {}
    id = ''

class HueDimmLight(HueBase):
    """ Node representing Hue Dimmable Light """

    def __init__(self, polyglot, primary, address, name, element_id, device, hub_idx):
        super().__init__(polyglot, primary, address, name, element_id, device, hub_idx)
        self.updateInfo()

    def start(self):
        try:
            self.transitiontime = int(self.getDriver('RR'))
        except:
            self.transitiontime = DEF_TRANSTIME
        self.updateInfo()

#    def query(self, command=None):
#        self.data = self.controller.hub[self.hub_idx].get_light(self.id)
#        if self.data is None:
#            return
#        self._updateInfo()
#        self.reportDrivers()

    def updateInfo(self):
        self.data = None
        zbc = None
        if self.controller.lights[self.hub_idx] is None:
            return
        try:
            for data in self.controller.lights[self.hub_idx]:
                if data['id'] == self.element_id:
                    self.data = data
                    break
            if self.data is None:
                LOGGER.info(f"Can't find light in bridge output, removing the node {self.element_id}")
                self.poly.delNode(self.address)
                return
            for parent_dev in self.controller.devices[self.hub_idx]:
                for dev_service in parent_dev['services']:
                    if dev_service['rtype'] == 'zigbee_connectivity':
                        zbc = dev_service['rid']
                    if dev_service['rid'] == self.element_id and dev_service['rtype'] == 'light':
                        self.parent_device_id = parent_dev['id']
                        self.zigbee_connectivity_id = zbc
                        break
        except KeyError:
            LOGGER.error(f'Node {self.address} no longer exists')
            self.controller.delNode(self.address)
            return
        self._updateInfo()

    def _updateInfo(self):
        if self.on is not None:
            if self.on != self.data['on']['on']:
                if self.data['on']['on']:
                    self.reportCmd('DON')
                else:
                    self.reportCmd('DOF')
        self.on = self.data['on']['on']
        self.brightness = self.data['dimming']['brightness']
        self.st = self.data['dimming']['brightness']

        self.setDriver('GV5', self.brightness)

        if self.on:
            self.setDriver('ST', self.st)
        else:
            self.setDriver('ST', 0)
        self.setDriver('RR', self.transitiontime)
        for zbc in self.controller.zigbee_connectivity[self.hub_idx]:
            if zbc['id'] == self.zigbee_connectivity_id:
                if zbc['status'] == 'connected':
                    self.reachable = 1
                else:
                    self.reachable = 0
        self.setDriver('GV6', self.reachable)
        return True

    def _send_command(self, command, transtime=None, checkOn=True):
        """ generic method to send command to light """
        if transtime is None:
            transtime = self.transitiontime
        if transtime != DEF_TRANSTIME:
            command['dynamics'] = { 'duration': int(transtime) }
        if checkOn and self.on is False:
            command['on'] = {'on': True}
            self.on = True
            if self.saved_brightness:
                # Attempt to restore saved brightness
                if 'dimming' not in command:
                    command['dimming'] = {'brightness': self.saved_brightness}
                self.saved_brightness = None
        return self.controller.hub[self.hub_idx].set_light(self.element_id, command)

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'RR', 'value': 400, 'uom': 42},
                {'driver': 'GV6', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'DON': HueBase.setBaseCtl, 'DOF': HueBase.setBaseCtl, 'QUERY': HueBase.query,
                   'DFON': HueBase.setBaseCtl, 'DFOF': HueBase.setBaseCtl, 'BRT': HueBase.setBaseCtl,
                   'DIM': HueBase.setBaseCtl, 'FDUP': HueBase.setBaseCtl, 'FDDOWN': HueBase.setBaseCtl,
                   'FDSTOP': HueBase.setBaseCtl, 'SET_BRI': HueBase.setBrightness, 'RR': HueBase.setTransition,
                   'SET_ALERT': HueBase.setAlert
               }

    id = 'DIMM_LIGHT'

class HueWhiteLight(HueDimmLight):
    """ Node representing Hue White Light """

    def _updateInfo(self):
        super()._updateInfo()
        if self.data['color_temperature']['mirek_valid']:
            self.ct = kel2mired(self.data['color_temperature']['mirek'])
        else:
            self.ct = 0
        self.setDriver('CLITEMP', self.ct)
        return True

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'RR', 'value': 400, 'uom': 42},
                {'driver': 'GV6', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'DON': HueBase.setBaseCtl, 'DOF': HueBase.setBaseCtl, 'QUERY': HueBase.query,
                   'DFON': HueBase.setBaseCtl, 'DFOF': HueBase.setBaseCtl, 'BRT': HueBase.setBaseCtl,
                   'DIM': HueBase.setBaseCtl, 'FDUP': HueBase.setBaseCtl, 'FDDOWN': HueBase.setBaseCtl,
                   'FDSTOP': HueBase.setBaseCtl, 'SET_BRI': HueBase.setBrightness, 'RR': HueBase.setTransition,
                   'CLITEMP': HueBase.setCt, 'SET_ALERT': HueBase.setAlert, 'SET_CTBR': HueBase.setCtBri
               }

    id = 'WHITE_LIGHT'

class HueColorLight(HueDimmLight):
    """ Node representing Hue Color Light """

    def _updateInfo(self):
        super()._updateInfo()
        #self.effect = self.data['state']['effect']
        self.color_x = round(float(self.data['color']['xy']['x']), 4)
        self.color_y = round(float(self.data['color']['xy']['y']), 4)
        #self.hue = self.data['state']['hue']
        #self.saturation = self.data['state']['sat']
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        #self.setDriver('GV3', self.hue)
        #self.setDriver('GV4', self.saturation)
        return True

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'GV4', 'value': 0, 'uom': 100},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'RR', 'value': 400, 'uom': 42},
                {'driver': 'GV6', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'DON': HueBase.setBaseCtl, 'DOF': HueBase.setBaseCtl, 'QUERY': HueBase.query,
                   'DFON': HueBase.setBaseCtl, 'DFOF': HueBase.setBaseCtl, 'BRT': HueBase.setBaseCtl,
                   'DIM': HueBase.setBaseCtl, 'FDUP': HueBase.setBaseCtl, 'FDDOWN': HueBase.setBaseCtl,
                   'FDSTOP': HueBase.setBaseCtl, 'SET_BRI': HueBase.setBrightness, 'RR': HueBase.setTransition,
                   'SET_COLOR': HueBase.setColor,
                   'SET_COLOR_RGB': HueBase.setColorRGB, 'SET_COLOR_XY': HueBase.setColorXY, 'SET_ALERT': HueBase.setAlert,
                   'SET_EFFECT': HueBase.setEffect
               }

    id = 'COLOR_LIGHT'

class HueEColorLight(HueColorLight):
    """ Node representing Hue Color Light """

    def _updateInfo(self):
        super()._updateInfo()
        if self.data['color_temperature']['mirek']:
            self.ct = kel2mired(self.data['color_temperature']['mirek'])
            self.setDriver('CLITEMP', self.ct)
        return True



    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'GV4', 'value': 0, 'uom': 100},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'RR', 'value': 400, 'uom': 42},
                {'driver': 'GV6', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'DON': HueBase.setBaseCtl, 'DOF': HueBase.setBaseCtl, 'QUERY': HueBase.query,
                   'DFON': HueBase.setBaseCtl, 'DFOF': HueBase.setBaseCtl, 'BRT': HueBase.setBaseCtl,
                   'DIM': HueBase.setBaseCtl, 'FDUP': HueBase.setBaseCtl, 'FDDOWN': HueBase.setBaseCtl,
                   'FDSTOP': HueBase.setBaseCtl, 'SET_BRI': HueBase.setBrightness, 'RR': HueBase.setTransition,
                   'SET_COLOR': HueBase.setColor,
                   'CLITEMP': HueBase.setCt, 'SET_COLOR_RGB': HueBase.setColorRGB,
                   'SET_COLOR_XY': HueBase.setColorXY, 'SET_ALERT': HueBase.setAlert, 'SET_EFFECT': HueBase.setEffect,
                   'SET_CTBR': HueBase.setCtBri
               }

    id = 'ECOLOR_LIGHT'

class HueGroup(HueBase):
    """ Node representing a group of Hue Lights """

    def __init__(self, polyglot, primary, address, name, element_id, device, hub_idx):
        super().__init__(polyglot, primary, address, name, element_id, device, hub_idx)
        self.devcount = None
        self.updateInfo()

    def start(self):
        try:
            self.transitiontime = int(self.getDriver('RR'))
        except:
            self.transitiontime = DEF_TRANSTIME
        self.updateInfo()

#    def query(self, command=None):
#        self.data = self.controller.hub[self.hub_idx].get_group(self.id)
#        if self.data is None:
#            return
#        try:
#            self._updateInfo()
#        except Exception as ex:
#            LOGGER.error(f"{self.data['type']} {self.data['name']} exception during update: {ex}")
#            return
#        self.reportDrivers()

    def updateInfo(self):
        self.data = None
        if self.controller.groups[self.hub_idx] is None:
            return
        try:
            for data in self.controller.groups[self.hub_idx]:
                if data['id'] == self.element_id:
                    self.data = data
                    break
            if self.data is None:
                LOGGER.info(f"Can't find group in bridge output, removing the node {self.element_id}")
                self.poly.delNode(self.address)
                return
        except KeyError:
            LOGGER.error(f'Node {self.address} no longer exists')
            self.controller.delNode(self.address)
            return
        self._updateInfo()

    def _updateInfo(self):
#        self.devcount = len(self.data['lights'])

#        if self.devcount < 1:
#            LOGGER.info("{} {} has {} lights, skipping updates".format(self.data['type'], self.data['name'], self.devcount))
#            return False
#        else:
#            self.setDriver('GV6', self.devcount)

        self.on = self.data['on']['on']
#        if self.all_on != self.data['state']['all_on']:
#            if self.data['state']['all_on']:
#                self.reportCmd('DON')
#                self.all_on = True
#            else:
#                self.reportCmd('DOF')
#                self.all_on = False

        self.brightness = self.data['dimming']['brightness']
        self.setDriver('GV5', self.brightness)

        self.st = self.data['dimming']['brightness']
        if self.on:
            self.setDriver('ST', self.st)
        else:
            self.setDriver('ST', 0)

#        self.alert = self.data['action']['alert']

        if 'mirek' in self.data['color_temperature']:
            self.ct = kel2mired(self.data['color_temperature']['mirek'])
            self.setDriver('CLITEMP', self.ct)
        else:
            self.setDriver('CLITEMP', 0)

#        if 'effect' in self.data['action']:
#            self.effect = self.data['action']['effect']

#        if 'xy' in self.data['action']:
#            (self.color_x, self.color_y) = [round(float(val), 4)
#                              for val in self.data['action'].get('xy',[0.0,0.0])]
#            self.setDriver('GV1', self.color_x)
#            self.setDriver('GV2', self.color_y)
#        else:
#            self.setDriver('GV1', 0)
#            self.setDriver('GV2', 0)

#        if 'hue' in self.data['action']:
#            self.hue = self.data['action']['hue']
#            self.setDriver('GV3', self.hue)
#        else:
#            self.setDriver('GV3', 0)

#        if 'sat' in self.data['action']:
#            self.saturation = self.data['action']['sat']
#            self.setDriver('GV4', self.saturation)
#        else:
#            self.setDriver('GV4', 0)

        self.setDriver('RR', self.transitiontime)
        return True

    def setHueScene(self, command):
        requested_scene_id = int(command.get('value'))
        for hue_scene in self.controller.scene_lookup:
            if hue_scene['hub'] == self.hub_idx and hue_scene['group'] == self.group_id and hue_scene['idx'] == requested_scene_id:
                LOGGER.info(f"{self.data['name']} requested scene: {hue_scene['name']} ({requested_scene_id}), hue scene group_id: {hue_scene['group_id']}")
                return self._send_command({"scene": hue_scene['group_id']})
        LOGGER.error(f"{self.data['name']} does not seem to have scene index {requested_scene_id}")
        return False

    def _send_command(self, command, transtime=None, checkOn=True):
        """ generic method to send command to group """
        if transtime is None:
            transtime = self.transitiontime
        if transtime != DEF_TRANSTIME:
            command['dynamics'] = { 'duration': int(transtime) }
        if checkOn and self.on is False:
            command['on'] = {'on': True}
            self.on = True
            if self.saved_brightness:
                # Attempt to restore saved brightness
                if 'dimming' not in command:
                    command['dimming'] = { 'brightness': self.saved_brightness }
                self.saved_brightness = None
        return self.controller.hub[self.hub_idx].set_group(self.element_id, command)

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'GV4', 'value': 0, 'uom': 100},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'GV6', 'value': 0, 'uom': 56},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'RR', 'value': 400, 'uom': 42}
              ]

    commands = {
                   'DON': HueBase.setBaseCtl, 'DOF': HueBase.setBaseCtl, 'QUERY': HueBase.query,
                   'DFON': HueBase.setBaseCtl, 'DFOF': HueBase.setBaseCtl, 'BRT': HueBase.setBaseCtl,
                   'DIM': HueBase.setBaseCtl, 'FDUP': HueBase.setBaseCtl, 'FDDOWN': HueBase.setBaseCtl,
                   'FDSTOP': HueBase.setBaseCtl, 'SET_BRI': HueBase.setBrightness, 'RR': HueBase.setTransition,
                   'SET_COLOR': HueBase.setColor,
                   'CLITEMP': HueBase.setCt, 'SET_COLOR_RGB': HueBase.setColorRGB,
                   'SET_COLOR_XY': HueBase.setColorXY, 'SET_ALERT': HueBase.setAlert, 'SET_EFFECT': HueBase.setEffect,
                   'SET_CTBR': HueBase.setCtBri, 'SET_HSCENE': setHueScene
               }

    id = 'HUE_GROUP'
