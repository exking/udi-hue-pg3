#!/usr/bin/env python3
""" Phillips Hue Node Server for ISY """

import sys
import logging
import json
import time
from threading import Thread
import urllib3
import sseclient
import udi_interface
import huev2
from converters import id2addr
from node_types import HueEColorLight, HueGroup, HueMotion, HueLum, HueTemp, HueButton

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
        self.zigbee_connectivity = {}
        self.devices = {}
        self.groups = {}
        self.scenes = {}
        self.rooms = {}
        self.zones = {}
        self.motion_sensor = {}
        self.lum_sensor = {}
        self.temp_sensor = {}
        self.button = {}
        self.scene_lookup = []
        self.ignore_second_on = False
        self.stream_thread = {}
        self.stream_last_update = {}
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
        # Initial node setup.
        # define nodes for settings
        if self.parameters['debug']:
            LOGGER.setLevel(logging.DEBUG)
        if self.parameters['ignore_second_on']:
            LOGGER.debug('DON will be ignored if already on')
            self.ignore_second_on = True
        self.connect()
        self.discover()

    def stop(self):
        LOGGER.info('Hue NodeServer is stopping')

    def poll(self, polltype):
        for idx in self.hub.keys():
            self._check_streaming(idx)

    def data_handler(self, data):
        self.cust_data.load(data)

    def connect(self):
        custom_data_ip = False
        custom_data_user = False
        save_needed = False
        bridges = {}
        hub_list = []
        """ Connect to Phillips Hue Hub """
        # pylint: disable=broad-except
        # get hub settings
        if self.cust_data['bridge_ip']:
            bridge_ip = self.cust_data['bridge_ip']
            custom_data_ip = True
            LOGGER.info(f'Bridge IP found in the Database: {bridge_ip}')
        if self.cust_data['bridge_user']:
            bridge_user = self.cust_data['bridge_user']
            custom_data_user = True
            LOGGER.info('Bridge Username found in the Database.')
        if self.cust_data['bridges']:
            for idx, bridge in self.cust_data['bridges'].items():
                bridges[bridge['ip']] = bridge['user']
            LOGGER.info(f'Database has {len(bridges)} bridge(s) configuration')
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
                LOGGER.error(f"Failed to read bridges variable {self.parameters['bridges']} {ex}")
                return
            LOGGER.info(f'Reading bridges configuration: {hub_list}')
        else:
            if len(bridges) > 0:
                for hub in bridges.keys():
                    hub_list.append(hub)
                    LOGGER.info(f'Adding existing bridge {hub}')
            else:
                LOGGER.info('No bridge configuration found, trying discovery...')
                hub_list = huev2.HueBridge.discover_bridges()

        for hub_ip in hub_list:
            # Initialize structures
            hub_user = None

            if hub_ip in bridges:
                LOGGER.info(f'Found username for bridge {hub_ip} in the DB')
                hub_user = bridges[hub_ip]
            else:
                save_needed = True

            try:
                hub_conn = huev2.HueBridge( hub_ip, hub_user )
            except huev2.PhueRegistrationException:
                LOGGER.error('IP Address OK. Node Server not registered.')
                self.notices['myNotice'] = 'Please press the button on the Hue Bridge(s) and restart the node server within 30 seconds'
                continue
            except Exception as ex:
                LOGGER.error(f'Cannot find Hue Bridge: {ex}')
                continue  # bad ip Address:
            else:
                # ensure hub is connectable
                hub_ip = hub_conn.hub_ip
                self.hub[hub_ip] = hub_conn
                self.lights[hub_ip] = self.hub[hub_ip].get_lights()

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

    def _find_parent_dev(self, hub_idx, child_id, child_type):
        for parent_dev in self.devices[hub_idx]:
            for dev_service in parent_dev['services']:
                if dev_service['rid'] == child_id and dev_service['rtype'] == child_type:
                    return parent_dev['id']
        return None

    def _get_parent_dev_name(self, hub_idx, parent_id):
        for parent_dev in self.devices[hub_idx]:
            if parent_dev['id'] == parent_id:
                return parent_dev['metadata']['name']
        return None

    def _get_parent_dev_zbconn(self, hub_idx, parent_id):
        for parent_dev in self.devices[hub_idx]:
            if parent_dev['id'] == parent_id:
                for dev_service in parent_dev['services']:
                    if dev_service['rtype'] == 'zigbee_connectivity':
                        return dev_service['rid']
        return None

    def _get_all_devices(self, hub_idx):
        self.lights[hub_idx] = self.hub[hub_idx].get_lights()
        self.devices[hub_idx] = self.hub[hub_idx].get_devices()
        self.groups[hub_idx] = self.hub[hub_idx].get_groups()
        self.rooms[hub_idx] = self.hub[hub_idx].get_rooms()
        self.zones[hub_idx] = self.hub[hub_idx].get_zones()
        self.scenes[hub_idx] = self.hub[hub_idx].get_scenes()
        self.motion_sensor[hub_idx] = self.hub[hub_idx].get_motion()
        self.lum_sensor[hub_idx] = self.hub[hub_idx].get_lum()
        self.temp_sensor[hub_idx] = self.hub[hub_idx].get_temp()
        self.button[hub_idx] = self.hub[hub_idx].get_button()
        self.zigbee_connectivity[hub_idx] = self.hub[hub_idx].get_zigbee_connectivity()

    def discover(self, command=None):
        self.scene_lookup = []
        for idx in self.hub.keys():
            self._discover(idx)

    def _discover(self, hub_idx):
        """ Poll Hue for new lights/existing lights' statuses """
        if self.hub[hub_idx] is None or self.discovery is True:
            return True
        self.discovery = True
        LOGGER.info(f'Hub {hub_idx} Starting Hue discovery...')
        self._get_all_devices(hub_idx)

        if not self.lights[hub_idx]:
            LOGGER.error(f'Hub {hub_idx} Discover: Failed to read Lights from the Hue Bridge')
            self.discovery = False
            return False

        LOGGER.info(f'Hub {hub_idx} {len(self.lights[hub_idx])} bulbs found. Checking status and adding to ISY if necessary.')

        for light in self.lights[hub_idx]:
            address = id2addr(light['id'])
            name = light['metadata']['name']
            parent_dev = self._find_parent_dev(hub_idx, light['id'], 'light')
            zb_conn = self._get_parent_dev_zbconn(hub_idx, parent_dev)

            if not self.poly.getNode(address):
                if light['type'] == "light":
                    LOGGER.info(f'Hub {hub_idx} Found Extended Color Bulb: {name}({address})')
                    self.poly.addNode(HueEColorLight(self.poly, self.address, address, name, light['id'], light, hub_idx, parent_dev, zb_conn))
                else:
                    LOGGER.info(f"Hub {hub_idx} Found Unsupported {light['type']} Bulb: {name}({address})")

        motion_count = len(self.motion_sensor[hub_idx])
        LOGGER.info(f'Hub {hub_idx} {motion_count} motion sensors found. Checking status and adding to ISY if necessary.')
        if motion_count > 0:
            for motion in self.motion_sensor[hub_idx]:
                address = id2addr(motion['id'])
                parent_dev = self._find_parent_dev(hub_idx, motion['id'], 'motion')
                zb_conn = self._get_parent_dev_zbconn(hub_idx, parent_dev)
                name = self._get_parent_dev_name(hub_idx, parent_dev) + ' motion'

                if not self.poly.getNode(address):
                    LOGGER.info(f'Hub {hub_idx} Found Motion Sensor: {name}({address})')
                    self.poly.addNode(HueMotion(self.poly, self.address, address, name, motion['id'], motion, hub_idx, parent_dev, zb_conn))

        lum_count = len(self.lum_sensor[hub_idx])
        LOGGER.info(f'Hub {hub_idx} {lum_count} luminance sensors found. Checking status and adding to ISY if necessary.')
        if lum_count > 0:
            for lum in self.lum_sensor[hub_idx]:
                address = id2addr(lum['id'])
                parent_dev = self._find_parent_dev(hub_idx, lum['id'], 'light_level')
                zb_conn = self._get_parent_dev_zbconn(hub_idx, parent_dev)
                name = self._get_parent_dev_name(hub_idx, parent_dev) + ' luminance'

                if not self.poly.getNode(address):
                    LOGGER.info(f'Hub {hub_idx} Found Luminance Sensor: {name}({address})')
                    self.poly.addNode(HueLum(self.poly, self.address, address, name, lum['id'], lum, hub_idx, parent_dev, zb_conn))

        temp_count = len(self.temp_sensor[hub_idx])
        LOGGER.info(f'Hub {hub_idx} {temp_count} temperature sensors found. Checking status and adding to ISY if necessary.')
        if temp_count > 0:
            for temp in self.temp_sensor[hub_idx]:
                address = id2addr(temp['id'])
                parent_dev = self._find_parent_dev(hub_idx, temp['id'], 'temperature')
                zb_conn = self._get_parent_dev_zbconn(hub_idx, parent_dev)
                name = self._get_parent_dev_name(hub_idx, parent_dev) + ' temperature'

                if not self.poly.getNode(address):
                    LOGGER.info(f'Hub {hub_idx} Found Temperature Sensor: {name}({address})')
                    self.poly.addNode(HueTemp(self.poly, self.address, address, name, temp['id'], temp, hub_idx, parent_dev, zb_conn))

        button_count = len(self.button[hub_idx])
        LOGGER.info(f'Hub {hub_idx} {button_count} buttons found. Checking status and adding to ISY if necessary.')
        if button_count > 0:
            button_idx = 0
            for button in self.button[hub_idx]:
                address = id2addr(button['id'])
                parent_dev = self._find_parent_dev(hub_idx, button['id'], 'button')
                zb_conn = self._get_parent_dev_zbconn(hub_idx, parent_dev)
                name = self._get_parent_dev_name(hub_idx, parent_dev) + ' button ' + str(button_idx)
                button_idx += 1

                if not self.poly.getNode(address):
                    LOGGER.info(f'Hub {hub_idx} Found Button: {name}({address})')
                    self.poly.addNode(HueButton(self.poly, self.address, address, name, button['id'], button, hub_idx, parent_dev, zb_conn))

        LOGGER.info(f'Hub {hub_idx} {len(self.groups[hub_idx])} groups found. Checking status and adding to ISY if necessary.')

        for group in self.groups[hub_idx]:
            address = id2addr(group['id'])
            scene_idx = 0
            if group['owner']['rtype'] == 'room':
                for room in self.rooms[hub_idx]:
                    if room['id'] == group['owner']['rid']:
                        name = room['metadata']['name']
                        break
                for scene in self.scenes[hub_idx]:
                    if scene['group']['rtype'] == 'room' and scene['group']['rid'] == room['id']:
                        self.scene_lookup.append({ "hub": hub_idx, "group": group['id'], "idx": scene_idx, "id": scene['id'], "name": scene['metadata']['name']})
                        LOGGER.info(f"Hub {hub_idx} Room {name} {scene_idx}:{scene['id']}:{scene['metadata']['name']}")
                        scene_idx += 1
            elif group['owner']['rtype'] == 'zone':
                for zone in self.zones[hub_idx]:
                    if zone['id'] == group['owner']['rid']:
                        name = zone['metadata']['name']
                        break
                for scene in self.scenes[hub_idx]:
                    if scene['group']['rtype'] == 'zone' and scene['group']['rid'] == zone['id']:
                        self.scene_lookup.append({ "hub": hub_idx, "group": group['id'], "idx": scene_idx, "id": scene['id'], "name": scene['metadata']['name']})
                        LOGGER.info(f"Hub {hub_idx} Zone {name} {scene_idx}:{scene['id']}:{scene['metadata']['name']}")
                        scene_idx += 1
            elif group['owner']['rtype'] == 'bridge_home':
                name = 'All Lights'
            else:
                name = 'Unknown group'

            if not self.poly.getNode(address):
                self.poly.addNode(HueGroup(self.poly, self.address, address, name, group['id'], group, hub_idx, None, None))

#            scene_idx = 0
#            if len(self.hub) > 1:
#                address = 'huegrp'+hub_idx.split('.')[-1]+group_id
#            else:
#                address = 'huegrp'+group_id
#            if group_id == '0':
#                name = 'All Lights'
#            else:
#                name = data['name']
#
#            if 'lights' in data and len(data['lights']) > 0:
#                if not self.poly.getNode(address):
#                    LOGGER.info("Hub {} Found {} {} with {} light(s)".format(hub_idx, data['type'], name, len(data['lights'])))
#                    self.poly.addNode(HueGroup(self.poly, self.address, address, name, group_id, data, hub_idx))
#                    if self.scenes[hub_idx]:
#                        for scene_id, scene_data in self.scenes[hub_idx].items():
#                            if 'group' in scene_data:
#                                if scene_data['group'] == group_id:
#                                    self.scene_lookup.append({ "hub": hub_idx, "group": int(group_id), "idx": scene_idx, "id": scene_id, "name": scene_data['name']})
#                                    LOGGER.info(f"Hub {hub_idx} {data['type']} {name} {scene_data['type']} {scene_idx}:{scene_id}:{scene_data['name']}")
#                                    scene_idx += 1
#            else:
#                if self.poly.getNode(address):
#                    LOGGER.info("Hub {} {} {} does not have any lights in it, removing a node".format(hub_idx, data['type'], name))
#                    self.poly.delNode(address)

        LOGGER.info(f'Hub {hub_idx} Discovery complete')
        self._check_streaming(hub_idx)
        self.discovery = False
        return True

    def updateNodes(self, hub_idx):
        if self.hub[hub_idx] is None or self.discovery is True:
            return
        self._get_all_devices(hub_idx)
        for node in self.poly.getNodes().values():
            node.updateInfo()

    def updateInfo(self):
        pass

    def _check_streaming(self, hub_ip):
        if hub_ip not in self.stream_thread or self.stream_thread[hub_ip] is None:
            LOGGER.debug('Starting Event Streaming thread for the first time.')
            self._start_streaming(hub_ip)
        else:
            if self.stream_thread[hub_ip].is_alive():
                if (int(time.time()) - self.stream_last_update[hub_ip]) > 86400:
                    LOGGER.error('No updates from streaming thread for 24 hours, streaming hung up? Restarting the node server...')
                    self.poly.restart()
                    return False
                return True
            LOGGER.warning('Event Streaming thread died, attempting to restart.')
            self._start_streaming(hub_ip)
        return True

    def _start_streaming(self, hub_ip):
        self.stream_thread[hub_ip] = Thread(target=self._streaming_process, args=[hub_ip], daemon=True)
        self.stream_thread[hub_ip].start()
        self.stream_last_update[hub_ip] = int(time.time())

    def _streaming_process(self, hub_ip):
        headers = {
            'hue-application-key': self.hub[hub_ip].username,
            'Accept': 'text/event-stream'
        }
        url = f"https://{hub_ip}/eventstream/clip/v2"
        http = urllib3.PoolManager(cert_reqs="CERT_REQUIRED", ca_certs="hue.crt", assert_hostname=False)
        try:
            response = http.request('GET', url, preload_content=False, headers=headers)
        except Exception as e:
            LOGGER.error(f'REST Streaming Request Failed: {e}')
            http.clear()
            return
        client = sseclient.SSEClient(response)
        for event in client.events():  # returns a generator
            self.stream_last_update[hub_ip] = int(time.time())
            event_data = json.loads(event.data)
            for event_item in event_data:
                for event_chunk in event_item['data']:
                    if event_chunk['type'] in ['light','grouped_light','motion','light_level','temperature','button']:
                        address = id2addr(event_chunk['id'])
                        if address in self.poly.getNodes():
                            self.poly.getNode(address).process_event(event_chunk)
                        else:
                            LOGGER.debug(f'Received event {event_chunk} for unknown node')
                    elif event_chunk['type'] == 'zigbee_connectivity':
                        for node in self.poly.getNodes().values():
                            if hasattr(node, "zigbee_connectivity_id"):
                                if node.zigbee_connectivity_id == event_chunk['id']:
                                    node.process_connectivity(event_chunk)
                    elif event_chunk['type'] == 'scene':
                        for scene in self.scenes[hub_ip]:
                            if scene['id'] == event_chunk['id']:
                                LOGGER.info(f"Scene {scene['metadata']['name']} {scene['id']} is {scene['status']['active']}")
                    else:
                        LOGGER.debug(f"Received unknown event type {event_chunk['type']}: {event_chunk}")
        LOGGER.warning('Streaming Process exited')

    drivers = [{ 'driver': 'ST', 'value': 1, 'uom': 2 }]
    commands = {'DISCOVER': discover}
    id = 'HUEBR'


if __name__ == "__main__":
    try:
        poly = udi_interface.Interface("Hue")
        poly.start()
        Control(poly, 'huebridge', 'huebridge', 'Hue')
        poly.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
