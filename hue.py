#!/usr/bin/env python3
""" Phillips Hue Node Server for ISY """

from converters import id_2_addr
try:
    from httplib import BadStatusLine  # Python 2.x
except ImportError:
    from http.client import BadStatusLine  # Python 3.x
import udi_interface
from node_types import HueDimmLight, HueWhiteLight, HueColorLight, HueEColorLight, HueGroup
import sys
import socket
import phue
import logging
import json

LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom

class Control(udi_interface.Node):
    """ Phillips Hue Node Server """
    
    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)
        self.parameters = Custom(polyglot, 'customparams')
        self.cust_data = Custom(polyglot, 'customdata')
        self.notices = Custom(polyglot, 'notices')
        self.discovery = False
        self.hub = {}
        self.lights = {}
        self.groups = {}
        self.scenes = {}
        self.scene_lookup = []
        self.ignore_second_on = False
        self.poly.subscribe(polyglot.START, self.start, address)
        self.poly.subscribe(polyglot.CUSTOMPARAMS, self.parameter_handler)
        self.poly.subscribe(polyglot.CUSTOMDATA, self.data_handler)
        self.poly.subscribe(polyglot.POLL, self.poll)
        self.poly.subscribe(polyglot.STOP, self.stop)
        self.poly.ready()
        self.poly.addNode(self)
        LOGGER.info('Started Hue Protocol')
                        
    def start(self):
        self.poly.updateProfile()
        self.poly.Notices.clear()

    def parameter_handler(self, params):
        self.parameters.load(params)
        self.poly.Notices.clear()
        """ Initial node setup. """
        # define nodes for settings
        if not self.parameters['debug']:
            LOGGER.setLevel(logging.INFO)
        if self.parameters['ignore_second_on']:
            LOGGER.debug('DON will be ignored if already on')
            self.ignore_second_on = True
        self.connect()
        self.discover()

    def stop(self):
        LOGGER.info('Hue NodeServer is stopping')

    def poll(self, polltype):
        for idx in self.hub.keys():
            self.updateNodes(idx)

    def data_handler(self, data):
         self.cust_data.load(data)

    def connect(self):
        custom_data_ip = False
        custom_data_user = False
        save_needed = False
        bridges = {}
        bridges_list = None
        hub_list = []
        """ Connect to Phillips Hue Hub """
        # pylint: disable=broad-except
        # get hub settings
        if self.cust_data['bridge_ip']:
            bridge_ip = self.cust_data['bridge_ip']
            custom_data_ip = True
            LOGGER.info('Bridge IP found in the Database: {}'.format(bridge_ip))
        if self.cust_data['bridge_user']:
            bridge_user = self.cust_data['bridge_user']
            custom_data_user = True
            LOGGER.info('Bridge Username found in the Database.')
        if self.cust_data['bridges']:
            for idx, bridge in self.cust_data['bridges'].items():
                bridges[bridge['ip']] = bridge['user']
            LOGGER.info('Database has {} bridge(s) configuration'.format(len(bridges)))
        else:
            LOGGER.info('Saved bridges information is not found')
            if custom_data_ip and custom_data_user:
                LOGGER.info('Old custom data found in the DB, converting')
                data = {'0': {'ip': bridge_ip, 'user': bridge_user }}
                bridges[bridge_ip] = bridge_user
                self.cust_data['bridges'] = data

        if self.parameters['bridges']:
            try:
                hub_list = json.loads(self.parameters['bridges'])
            except Exception as ex:
                LOGGER.error('Failed to read bridges variable {} {}'.format(self.parameters['bridges'], ex))
                return
            LOGGER.info('Reading bridges configuration: {}'.format(hub_list))
        else:
            if len(bridges) > 0:
                for hub in bridges.keys():
                    hub_list.append(hub)
                    LOGGER.info('Adding existing bridge {}'.format(hub))
            else:
                LOGGER.info('No bridge configuration found, trying discovery...')
                hub_list = [ None ]

        for hub_ip in hub_list:
            ''' Initialize structures '''
            hub_user = None

            if hub_ip in bridges:
                LOGGER.info('Found username for bridge {} in the DB'.format(hub_ip))
                hub_user = bridges[hub_ip]
            else:
                save_needed = True

            try:
                hub_conn = phue.Bridge( hub_ip, hub_user )
            except phue.PhueRegistrationException:
                LOGGER.error('IP Address OK. Node Server not registered.')
                self.notices['myNotice'] = 'Please press the button on the Hue Bridge(s) and restart the node server within 30 seconds'
                continue
            except Exception:
                LOGGER.error('Cannot find Hue Bridge')
                continue  # bad ip Address:
            else:
                # ensure hub is connectable
                hub_ip = hub_conn.ip
                self.hub[hub_ip] = hub_conn
                self.lights[hub_ip] = self._get_lights(hub_ip)

                if self.lights[hub_ip]:
                    LOGGER.info('Connection OK')
                    hub_user = self.hub[hub_ip].username
                    bridges[hub_ip] = hub_user
                else:
                    LOGGER.error('Connect: Failed to read Lights from the Hue Bridge')
                    self.hub[hub_ip] = None
        if save_needed:
            idx = 0
            data = {}
            for hub_ip in bridges.keys():
                data[idx] = {'ip': hub_ip, 'user': bridges[hub_ip]}
                idx += 1
            if len(data) > 0:
                LOGGER.info('Saving usernames to DB')
                self.cust_data['bridges'] = data

    def discover(self, command=None):
        self.scene_lookup = []
        for idx in self.hub.keys():
            self._discover(idx)

    def _discover(self, hub_idx):
        """ Poll Hue for new lights/existing lights' statuses """
        if self.hub[hub_idx] is None or self.discovery == True:
            return True
        self.discovery = True
        LOGGER.info('Hub {} Starting Hue discovery...'.format(hub_idx))

        self.lights[hub_idx] = self._get_lights(hub_idx)
        if not self.lights[hub_idx]:
            LOGGER.error('Hub {} Discover: Failed to read Lights from the Hue Bridge'.format(hub_idx))
            self.discovery = False
            return False
        
        LOGGER.info('Hub {} {} bulbs found. Checking status and adding to ISY if necessary.'.format(hub_idx, len(self.lights[hub_idx])))

        for lamp_id, data in self.lights[hub_idx].items():
            address = id_2_addr(data['uniqueid'])
            name = data['name']
            
            if not self.poly.getNode(address):
                if data['type'] == "Extended color light":
                    LOGGER.info('Hub {} Found Extended Color Bulb: {}({})'.format(hub_idx, name, address))
                    self.poly.addNode(HueEColorLight(self.poly, self.address, address, name, lamp_id, data, hub_idx))
                elif data['type'] == "Color light":
                    LOGGER.info('Hub {} Found Color Bulb: {}({})'.format(hub_idx, name, address))
                    self.poly.addNode(HueColorLight(self.poly, self.address, address, name, lamp_id, data, hub_idx))
                elif data['type'] == "Color temperature light":
                    LOGGER.info('Hub {} Found White Ambiance Bulb: {}({})'.format(hub_idx, name, address))
                    self.poly.addNode(HueWhiteLight(self.poly, self.address, address, name, lamp_id, data, hub_idx))
                elif data['type'] == "Dimmable light":
                    LOGGER.info('Hub {} Found Dimmable Bulb: {}({})'.format(hub_idx, name, address))
                    self.poly.addNode(HueDimmLight(self.poly, self.address, address, name, lamp_id, data, hub_idx))
                else:
                    LOGGER.info('Hub {} Found Unsupported {} Bulb: {}({})'.format(hub_idx, data['type'], name, address))

        self.scenes[hub_idx] = self._get_scenes(hub_idx)
        if not self.scenes[hub_idx]:
            LOGGER.error('Hub {} Discover: Failed to read Scenes from the Hue Bridge'.format(hub_idx))
        
        self.groups[hub_idx] = self._get_groups(hub_idx)
        if not self.groups[hub_idx]:
            LOGGER.error('Hub {} Discover: Failed to read Groups from the Hue Bridge'.format(hub_idx))
            self.discovery = False
            return False

        LOGGER.info('Hub {} {} groups found. Checking status and adding to ISY if necessary.'.format(hub_idx, len(self.groups[hub_idx])))

        for group_id, data in self.groups[hub_idx].items():
            scene_idx = 0
            if len(self.hub) > 1:
                address = 'huegrp'+hub_idx.split('.')[-1]+group_id
            else:
                address = 'huegrp'+group_id
            if group_id == '0':
                name = 'All Lights'
            else:
                name = data['name']
            
            if 'lights' in data and len(data['lights']) > 0:
                if not self.poly.getNode(address):
                    LOGGER.info("Hub {} Found {} {} with {} light(s)".format(hub_idx, data['type'], name, len(data['lights'])))
                    self.poly.addNode(HueGroup(self.poly, self.address, address, name, group_id, data, hub_idx))
                    if self.scenes[hub_idx]:
                        for scene_id, scene_data in self.scenes[hub_idx].items():
                            if 'group' in scene_data:
                                if scene_data['group'] == group_id:
                                    self.scene_lookup.append({ "hub": hub_idx, "group": int(group_id), "idx": scene_idx, "id": scene_id, "name": scene_data['name']})
                                    LOGGER.info(f"Hub {hub_idx} {data['type']} {name} {scene_data['type']} {scene_idx}:{scene_id}:{scene_data['name']}")
                                    scene_idx += 1
            else:
                if self.poly.getNode(address):
                    LOGGER.info("Hub {} {} {} does not have any lights in it, removing a node".format(hub_idx, data['type'], name))
                    self.poly.delNode(address)
        
        LOGGER.info('Hub {} Discovery complete'.format(hub_idx))
        self.discovery = False
        return True

    def updateNodes(self, hub_idx):
        if self.hub[hub_idx] is None or self.discovery == True:
            return True
        self.lights[hub_idx] = self._get_lights(hub_idx)
        self.groups[hub_idx] = self._get_groups(hub_idx)
        try:
            for node in self.poly.getNodes().values():
                node.updateInfo()
        except Exception as ex:
            LOGGER.error(f'Exception during {hub_idx} nodes update: {ex}')
            return False
        return True

    def updateInfo(self):
        pass

    def _get_lights(self, hub_idx):
        if self.hub[hub_idx] is None:
            return None
        try:
            lights = self.hub[hub_idx].get_light()
        except BadStatusLine:
            LOGGER.error('Hue Bridge returned bad status line.')
            return None
        except phue.PhueRequestTimeout:
            LOGGER.error('Timed out trying to connect to Hue Bridge.')
            return None
        except socket.error:
            LOGGER.error("Can't contact Hue Bridge. " +
                         "Network communication issue.")
            return None
        except Exception as ex:
            LOGGER.error(f'Hue bridge exception {ex}')
            return None
        return lights

    def _get_groups(self, hub_idx):
        if self.hub[hub_idx] is None:
            return None
        try:
            groups = self.hub[hub_idx].get_group()
        except BadStatusLine:
            LOGGER.error('Hue Bridge returned bad status line.')
            return None
        except phue.PhueRequestTimeout:
            LOGGER.error('Timed out trying to connect to Hue Bridge.')
            return None
        except socket.error:
            LOGGER.error("Can't contact Hue Bridge. " +
                         "Network communication issue.")
            return None
        except Exception as ex:
            LOGGER.error(f'Hue bridge exception {ex}')
            return None
        return groups

    def _get_scenes(self, hub_idx):
        if self.hub[hub_idx] is None:
            return None
        try:
            scenes = self.hub[hub_idx].get_scene()
        except BadStatusLine:
            LOGGER.error('Hue Bridge returned bad status line.')
            return None
        except phue.PhueRequestTimeout:
            LOGGER.error('Timed out trying to connect to Hue Bridge.')
            return None
        except socket.error:
            LOGGER.error("Can't contact Hue Bridge. " +
                         "Network communication issue.")
            return None
        except Exception as ex:
            LOGGER.error(f'Hue bridge exception {ex}')
            return None
        return scenes

    drivers = [{ 'driver': 'ST', 'value': 1, 'uom': 2 }]
    commands = {'DISCOVER': discover}
    id = 'HUEBR'


if __name__ == "__main__":
    try:
        """
        Grab the "HUE" variable from the .polyglot/.env file. This is where
        we tell it what profile number this NodeServer is.
        """
        poly = udi_interface.Interface("Hue")
        poly.start()
        Control(poly, 'huebridge', 'huebridge', 'Hue')
        poly.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
