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

HUE_EFFECTS = ['no_effect', 'prism', 'opal', 'glisten', 'sparkle', 'fire', 'candle', 'underwater', 'cosmos', 'sunbeam', 'enchant']
HUE_TIMED_EFFECTS = ['no_effect', 'sunrise', 'sunset']
HUE_ALERTS = ['none', 'breathe']

class HueBase(udi_interface.Node):
    """ Base class for lights and groups """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
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
        self.zigbee_connectivity_id = zb_conn
        self.parent_device_id = parent_dev
        self.reachable = 0

    def query(self):
        pass

    def set_base_ctl(self, command):
        """ Basic On/Off and brightness controls """
        cmd = command.get('cmd')
        hue_command = {}

        # transition time for FastOn/Off
        if cmd in [ 'DFON', 'DFOF' ]:
            trans = 0
        else:
            trans = self.transitiontime

        if cmd in ['DON', 'DFON']:
            val = command.get('value')
            if val:
                self.brightness = self._validate_brightness(int(val))
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
                direction = 'up'
                self.brightness += increment
            elif cmd == 'DIM':
                increment = DEF_INCREMENT
                direction = 'down'
                self.brightness -= increment
            elif cmd == 'FDUP':
                trans = FADE_TRANSTIME
                direction = 'up'
                increment = 100
            elif cmd == 'FDDOWN':
                trans = FADE_TRANSTIME
                direction = 'down'
                increment = 100
            else:
                # FDSTOP
                direction = 'stop'
                increment = 0
            self.st = self.brightness
            hue_command['dimming_delta'] = { 'action': direction, 'brightness_delta': increment }
            self.setDriver('GV5', self.brightness)
            self._send_command(hue_command, trans)
        else:
            LOGGER.error(f'set_base_ctl received an unknown command: {cmd}')
        self.setDriver('ST', self.st)

    def set_brightness(self, command):
        self.brightness = self._validate_brightness(int(command.get('value')))
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        hue_command = { 'dimming': {'brightness': self.brightness }}
        return self._send_command(hue_command)

    def set_transition(self, command):
        self.transitiontime = int(command.get('value'))
        self.setDriver('RR', self.transitiontime)
        return True

    def set_alert(self, command):
        val = int(command.get('value')) - 1
        #self.alert = HUE_ALERTS[val]
        self.alert = 'breathe'
        hue_command = {'alert': {'action': self.alert}}
        return self._send_command(hue_command)

    def _validate_brightness(self, brightness):
        if brightness > 100:
            brightness = 100
        elif brightness < 0:
            brightness = 0
        self.st = brightness
        return brightness

    def set_ct(self, command):
        self.ct = int(command.get('value'))
        self.setDriver('CLITEMP', self.ct)
        hue_command = {'color_temperature': { 'mirek': kel2mired(self.ct) }}
        return self._send_command(hue_command)

    def set_ct_bri(self, command):
        query = command.get('query')
        self.brightness = self._validate_brightness(int(query.get('BR.uom100')))
        self.ct = int(query.get('K.uom26'))
        self.setDriver('CLITEMP', self.ct)
        self.setDriver('ST', self.st)
        self.setDriver('GV5', self.brightness)
        hue_command = { 'color_temperature': {'mirek': kel2mired(self.ct)}, 'dimming': {'brightness': self.brightness }}
        return self._send_command(hue_command)

    def set_color_rgb(self, command):
        query = command.get('query')
        color_r = int(query.get('R.uom100'))
        color_g = int(query.get('G.uom100'))
        color_b = int(query.get('B.uom100'))
        transtime = int(query.get('D.uom42'))
        self.brightness = self._validate_brightness(int(query.get('BR.uom100')))
        (self.color_x, self.color_y) = RGB_2_xy(color_r, color_g, color_b)
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}, 'dimming': {'brightness': self.brightness}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        return self._send_command(hue_command, transtime)

    def set_color_xy(self, command):
        query = command.get('query')
        self.color_x = float(query.get('X.uom56'))
        self.color_y = float(query.get('Y.uom56'))
        transtime = int(query.get('D.uom42'))
        self.brightness = self._validate_brightness(int(query.get('BR.uom100')))
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}, 'dimming': {'brightness': self.brightness}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        self.setDriver('GV5', self.brightness)
        self.setDriver('ST', self.st)
        return self._send_command(hue_command, transtime)

    def set_color(self, command):
        c_id = int(command.get('value')) - 1
        (self.color_x, self.color_y) = color_xy(c_id)
        hue_command = {'color': {'xy': {'x': self.color_x, 'y': self.color_y}}}
        self.setDriver('GV1', self.color_x)
        self.setDriver('GV2', self.color_y)
        return self._send_command(hue_command)

    def set_effect(self, command):
        val = int(command.get('value')) - 1
        self.effect = HUE_EFFECTS[val]
        hue_command = { 'effects_v2': {'effect': {'action': self.effect}}} 
        return self._send_command(hue_command)

    def set_timed_effect(self, command):
        val = int(command.get('value')) - 1
        self.effect = HUE_TIMED_EFFECTS[val]
        hue_command = { 'timed_effects': {'effect': self.effect, 'duration': 800}} 
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

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
        super().__init__(polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn)
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
        if 'dimming' in self.data:
            self.brightness = self.data['dimming']['brightness']
            self.st = self.data['dimming']['brightness']
        else:
           self.st = 100
           self.brightness = 100

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
                   'DON': HueBase.set_base_ctl, 'DOF': HueBase.set_base_ctl, 'QUERY': HueBase.query,
                   'DFON': HueBase.set_base_ctl, 'DFOF': HueBase.set_base_ctl, 'BRT': HueBase.set_base_ctl,
                   'DIM': HueBase.set_base_ctl, 'FDUP': HueBase.set_base_ctl, 'FDDOWN': HueBase.set_base_ctl,
                   'FDSTOP': HueBase.set_base_ctl, 'SET_BRI': HueBase.set_brightness, 'RR': HueBase.set_transition,
                   'SET_ALERT': HueBase.set_alert
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

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV5', 'value': 0, 'uom': 100},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'RR', 'value': 400, 'uom': 42},
                {'driver': 'GV6', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'DON': HueBase.set_base_ctl, 'DOF': HueBase.set_base_ctl, 'QUERY': HueBase.query,
                   'DFON': HueBase.set_base_ctl, 'DFOF': HueBase.set_base_ctl, 'BRT': HueBase.set_base_ctl,
                   'DIM': HueBase.set_base_ctl, 'FDUP': HueBase.set_base_ctl, 'FDDOWN': HueBase.set_base_ctl,
                   'FDSTOP': HueBase.set_base_ctl, 'SET_BRI': HueBase.set_brightness, 'RR': HueBase.set_transition,
                   'CLITEMP': HueBase.set_ct, 'SET_ALERT': HueBase.set_alert, 'SET_CTBR': HueBase.set_ct_bri
               }

    id = 'WHITE_LIGHT'

class HueColorLight(HueDimmLight):
    """ Node representing Hue Color Light """

    def _updateInfo(self):
        super()._updateInfo()
        if 'color' in self.data:
            self.color_x = round(float(self.data['color']['xy']['x']), 4)
            self.color_y = round(float(self.data['color']['xy']['y']), 4)
            self.setDriver('GV1', self.color_x)
            self.setDriver('GV2', self.color_y)

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
                   'DON': HueBase.set_base_ctl, 'DOF': HueBase.set_base_ctl, 'QUERY': HueBase.query,
                   'DFON': HueBase.set_base_ctl, 'DFOF': HueBase.set_base_ctl, 'BRT': HueBase.set_base_ctl,
                   'DIM': HueBase.set_base_ctl, 'FDUP': HueBase.set_base_ctl, 'FDDOWN': HueBase.set_base_ctl,
                   'FDSTOP': HueBase.set_base_ctl, 'SET_BRI': HueBase.set_brightness, 'RR': HueBase.set_transition,
                   'SET_COLOR': HueBase.set_color,
                   'SET_COLOR_RGB': HueBase.set_color_rgb, 'SET_COLOR_XY': HueBase.set_color_xy, 'SET_ALERT': HueBase.set_alert,
                   'SET_EFFECT': HueBase.set_effect
               }

    id = 'COLOR_LIGHT'

class HueEColorLight(HueColorLight):
    """ Node representing Hue Color Light """

    def _updateInfo(self):
        super()._updateInfo()
        if 'color_temperature' in self.data:
            if self.data['color_temperature']['mirek']:
                self.ct = kel2mired(self.data['color_temperature']['mirek'])
                self.setDriver('CLITEMP', self.ct)


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
                   'DON': HueBase.set_base_ctl, 'DOF': HueBase.set_base_ctl, 'QUERY': HueBase.query,
                   'DFON': HueBase.set_base_ctl, 'DFOF': HueBase.set_base_ctl, 'BRT': HueBase.set_base_ctl,
                   'DIM': HueBase.set_base_ctl, 'FDUP': HueBase.set_base_ctl, 'FDDOWN': HueBase.set_base_ctl,
                   'FDSTOP': HueBase.set_base_ctl, 'SET_BRI': HueBase.set_brightness, 'RR': HueBase.set_transition,
                   'SET_COLOR': HueBase.set_color,
                   'CLITEMP': HueBase.set_ct, 'SET_COLOR_RGB': HueBase.set_color_rgb,
                   'SET_COLOR_XY': HueBase.set_color_xy, 'SET_ALERT': HueBase.set_alert, 'SET_EFFECT': HueBase.set_effect,
                   'SET_CTBR': HueBase.set_ct_bri
               }

    id = 'ECOLOR_LIGHT'

class HueGroup(HueBase):
    """ Node representing a group of Hue Lights """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
        super().__init__(polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn)
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

    def set_hue_scene(self, command):
        requested_scene_id = int(command.get('value'))
        for hue_scene in self.controller.scene_lookup:
            if hue_scene['hub'] == self.hub_idx and hue_scene['group'] == self.element_id and hue_scene['idx'] == requested_scene_id:
                LOGGER.info(f"{self.name} requested scene: {hue_scene['name']} ({requested_scene_id}), hue scene id: {hue_scene['id']}")
                return self.controller.hub[self.hub_idx].set_scene(hue_scene['id'], {'recall': {'action': 'active'}})
        LOGGER.error(f"{self.name} does not seem to have scene index {requested_scene_id}")
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
                   'DON': HueBase.set_base_ctl, 'DOF': HueBase.set_base_ctl, 'QUERY': HueBase.query,
                   'DFON': HueBase.set_base_ctl, 'DFOF': HueBase.set_base_ctl, 'BRT': HueBase.set_base_ctl,
                   'DIM': HueBase.set_base_ctl, 'FDUP': HueBase.set_base_ctl, 'FDDOWN': HueBase.set_base_ctl,
                   'FDSTOP': HueBase.set_base_ctl, 'SET_BRI': HueBase.set_brightness, 'RR': HueBase.set_transition,
                   'SET_COLOR': HueBase.set_color,
                   'CLITEMP': HueBase.set_ct, 'SET_COLOR_RGB': HueBase.set_color_rgb,
                   'SET_COLOR_XY': HueBase.set_color_xy, 'SET_ALERT': HueBase.set_alert, 'SET_EFFECT': HueBase.set_effect,
                   'SET_CTBR': HueBase.set_ct_bri, 'SET_HSCENE': set_hue_scene
               }

    id = 'HUE_GROUP'


class HueMotion(udi_interface.Node):
    """ Node representing Hue Motion Sensor """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
        super().__init__(polyglot, primary, address, name)
        self.controller = self.poly.getNode(self.primary)
        self.name = name
        self.address = address
        self.element_id = element_id
        self.data = element
        self.hub_idx = hub_idx
        self.zigbee_connectivity_id = zb_conn
        self.parent_device_id = parent_dev
        self.reachable = 0
        self.updateInfo()

    def query(self):
        pass

    def updateInfo(self):
        self.data = None
        zbc = None
        if self.controller.lights[self.hub_idx] is None:
            return
        try:
            for data in self.controller.motion_sensor[self.hub_idx]:
                if data['id'] == self.element_id:
                    self.data = data
                    break
            if self.data is None:
                LOGGER.info(f"Can't find motion sensor {self.name} in bridge output, removing the node {self.element_id}")
                self.poly.delNode(self.address)
                return
        except KeyError:
            LOGGER.error(f'Node {self.address} no longer exists')
            self.controller.delNode(self.address)
            return
        self._updateInfo()

    def _updateInfo(self):
        if self.data['motion']['motion_report']['motion']:
            self.setDriver('ST', 1)
        else:
            self.setDriver('ST', 0)

        for zbc in self.controller.zigbee_connectivity[self.hub_idx]:
            if zbc['id'] == self.zigbee_connectivity_id:
                if zbc['status'] == 'connected':
                    self.reachable = 1
                else:
                    self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    def process_event(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if 'motion' in event:
            if event['motion']['motion_report']['motion']:
                self.reportCmd('DON')
                self.setDriver('ST', 1)
            else:
                self.reportCmd('DOF')
                self.setDriver('ST', 0)

    def process_connectivity(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if event['status'] == 'connected':
            self.reachable = 1
        else:
            self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 2}
              ]

    commands = {
                   'QUERY':query
               }

    id = 'HUEMOTION'


class HueLum(udi_interface.Node):
    """ Node representing Hue Motion Sensor """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
        super().__init__(polyglot, primary, address, name)
        self.controller = self.poly.getNode(self.primary)
        self.name = name
        self.address = address
        self.element_id = element_id
        self.data = element
        self.hub_idx = hub_idx
        self.zigbee_connectivity_id = zb_conn
        self.parent_device_id = parent_dev
        self.reachable = 0
        self.updateInfo()

    def query(self):
        pass

    def updateInfo(self):
        self.data = None
        zbc = None
        if self.controller.lights[self.hub_idx] is None:
            return
        try:
            for data in self.controller.lum_sensor[self.hub_idx]:
                if data['id'] == self.element_id:
                    self.data = data
                    break
            if self.data is None:
                LOGGER.info(f"Can't find luminance sensor {self.name} in bridge output, removing the node {self.element_id}")
                self.poly.delNode(self.address)
                return
        except KeyError:
            LOGGER.error(f'Node {self.address} no longer exists')
            self.controller.delNode(self.address)
            return
        self._updateInfo()

    def _updateInfo(self):
        if self.data['light']['light_level_valid']:
            light_level = self.data['light']['light_level_report']['light_level']
            self.setDriver('ST', light_level)

        for zbc in self.controller.zigbee_connectivity[self.hub_idx]:
            if zbc['id'] == self.zigbee_connectivity_id:
                if zbc['status'] == 'connected':
                    self.reachable = 1
                else:
                    self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    def process_event(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if 'light' in event:
            light_level = event['light']['light_level_report']['light_level']
            self.setDriver('ST', light_level)

    def process_connectivity(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if event['status'] == 'connected':
            self.reachable = 1
        else:
            self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 0}
              ]

    commands = {
                   'QUERY':query
               }

    id = 'HUELUM'

class HueTemp(udi_interface.Node):
    """ Node representing Hue Motion Sensor """

    def __init__(self, polyglot, primary, address, name, element_id, element, hub_idx, parent_dev, zb_conn):
        super().__init__(polyglot, primary, address, name)
        self.controller = self.poly.getNode(self.primary)
        self.name = name
        self.address = address
        self.element_id = element_id
        self.data = element
        self.hub_idx = hub_idx
        self.zigbee_connectivity_id = zb_conn
        self.parent_device_id = parent_dev
        self.reachable = 0
        self.updateInfo()

    def query(self):
        pass

    def updateInfo(self):
        self.data = None
        zbc = None
        if self.controller.lights[self.hub_idx] is None:
            return
        try:
            for data in self.controller.temp_sensor[self.hub_idx]:
                if data['id'] == self.element_id:
                    self.data = data
                    break
            if self.data is None:
                LOGGER.info(f"Can't find temperature sensor {self.name} in bridge output, removing the node {self.element_id}")
                self.poly.delNode(self.address)
                return
        except KeyError:
            LOGGER.error(f'Node {self.address} no longer exists')
            self.controller.delNode(self.address)
            return
        self._updateInfo()

    def _updateInfo(self):
        if self.data['temperature']['temperature_valid']:
            temp_c = self.data['temperature']['temperature_report']['temperature']
            self.setDriver('ST', temp_c)

        for zbc in self.controller.zigbee_connectivity[self.hub_idx]:
            if zbc['id'] == self.zigbee_connectivity_id:
                if zbc['status'] == 'connected':
                    self.reachable = 1
                else:
                    self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    def process_event(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if 'temperature' in event:
            temp_c =  event['temperature']['temperature_report']['temperature']
            self.setDriver('ST', temp_c)

    def process_connectivity(self, event):
        LOGGER.debug(f'{self.name} processing event {json.dumps(event)}')
        if event['status'] == 'connected':
            self.reachable = 1
        else:
            self.reachable = 0
#        self.setDriver('GV6', self.reachable)

    drivers = [ {'driver': 'ST', 'value': 0, 'uom': 4}
              ]

    commands = {
                   'QUERY':query
               }

    id = 'HUETEMP'
