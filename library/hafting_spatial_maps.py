import os, sys
import numpy as np
import multiprocessing as mp
import functools
import itertools
import cv2
from numba import jit, njit
import matplotlib.pyplot as plt
from scipy import signal

PROJECT_PATH = os.getcwd()
sys.path.append(PROJECT_PATH)

from library.map_utils import _compute_unmasked_ratemap, _temp_spike_map, _temp_occupancy_map, _speed_bins, _speed2D
from core.spatial import Position2D
from library.ensemble_space import Cell
from core.spikes import SpikeTrain



class SpatialSpikeTrain2D():

    def __init__(self, input_dict: dict, **kwargs):
        # spike_train: SpikeTrain, position: Position2D, **kwargs):
        self._input_dict = input_dict
        self.spike_obj, self.position = self._read_input_dict()
        self.spike_times = self.spike_obj.event_times
        self.t, self.x, self.y = self.position.t, self.position.x, self.position.y

        assert len(self.t) == len(self.x) == len(self.y)

        if 'session_metadata' in kwargs:
            self.session_metadata = kwargs['session_metadata']
        else:
            self.session_metadata = None
        if self.position.arena_height != None and self.position.arena_width != None:
            self.arena_size = (self.position.arena_height, self.position.arena_width)
        else:
            self.arena_size = None

        if 'speed_bounds' in kwargs:
            self.speed_bounds = kwargs['speed_bounds']
        else:
            self.speed_bounds = (0, 100)


        self.spike_x, self.spike_y, self.new_spike_times = self.get_spike_positions()

        assert len(self.spike_x) == len(self.spike_y) == len(self.new_spike_times)

        self.stats_dict = self._init_stats_dict()

    def _read_input_dict(self):
        spike_obj = None
        position = None

        assert ('spike_train' not in self._input_dict and 'cell' in self._input_dict) or ('spike_train' in self._input_dict and 'cell' not in self._input_dict)

        if 'spike_train' in self._input_dict:
            spike_obj = self._input_dict['spike_train']
            assert isinstance(spike_obj, SpikeTrain)
        elif 'cell' in self._input_dict:
            spike_obj = self._input_dict['cell']
            assert isinstance(spike_obj, Cell)

        if 'position' in self._input_dict:
            position = self._input_dict['position']
            assert isinstance(position, Position2D)

        return spike_obj, position


    def _init_stats_dict(self):
        stats_dict = {}

        map_names = ['autocorr', 'binary', 'spatial_tuning', 'pos_vs_speed', 'rate_vs_time', 'hafting', 'occupancy', 'rate', 'spike', 'map_blobs']

        for key in map_names:
            stats_dict[key] = None

        return stats_dict

    def add_map_to_stats(self, map_name, map_class):
        # print(self.stats_dict)
        assert map_name in self.stats_dict, 'check valid map types to add to stats dict, map type not in stats dict'
        # assert type(map_class) != np.ndarray and type(map_class) != list
        self.stats_dict[map_name] = map_class

    def get_map(self, map_name):
        assert map_name in self.stats_dict, 'check valid map types to add to stats dict, map type not in stats dict'
        map_obj = self.stats_dict[map_name]

        hafting_maps = {'rate': HaftingRateMap, 'spike': HaftingSpikeMap, 'occupancy': HaftingOccupancyMap}

        # map_functions = {'binary': binary_map, 'autocrrelation': autocorrelation, 'spatial_tuning': spatial_tuning_curve}

        if map_obj is None and map_name in hafting_maps:
            map_obj = hafting_maps[map_name](self)
            self.stats_dict[map_name] = map_obj

        # elif map_obj == None and map_name in map_functions:
        #     map_data = map_functions[map_name](self)
        #     self.stats_dict[map_name] = map_data

        return map_obj

    #def spike_pos(ts, x, y, t, cPost, shuffleSpks, shuffleCounter=True):
    def get_spike_positions(self):
        # if type(self.spike_times) == list:
        #     spike_array = np.array(self.spike_times)
        # else:
        #     spike_array = self.spike_times
        # time_step_t = self.t[1] - self.t[0]
        # spike_index = []
        # for i in range(len(self.t)):
        #     id_set_1 = np.where(spike_array >= self.t[i])[0]
        #     id_set_2 = np.where(spike_array < self.t[i] + time_step_t)[0]
        #     for id in id_set_1:
        #         if id in id_set_2 and id not in spike_index:
        #             spike_index.append(id)

        # # def _match(time, time_index, spike_time):
        # #     if spike_time >= time and spike_time < time + time_step_t:
        # #         return time_index

        # # spike_index = list(filter(_match(self.t, range(len(self.t)), self.spike_times)))
        # return np.array(self.x)[spike_index], np.array(self.y)[spike_index]

        v = _speed2D(self.x, self.y, self.t)
        x, y, t = _speed_bins(self.speed_bounds[0], self.speed_bounds[1], v, self.x, self.y, self.t)

        cPost = np.copy(t)

        N = len(self.spike_times)
        spike_positions_x = np.zeros((N, 1))
        spike_positions_y = np.zeros_like(spike_positions_x)
        new_spike_times = np.zeros_like(spike_positions_x)
        count = -1 # need to subtract 1 because the python indices start at 0 and MATLABs at 1


        for index in range(N):

            tdiff = (t -self.spike_times[index])**2
            tdiff2 = (cPost-self.spike_times[index])**2
            m = np.amin(tdiff)
            ind = np.where(tdiff == m)[0]

            m2 = np.amin(tdiff2)
            #ind2 = np.where(tdiff2 == m2)[0]

            if m == m2:
                count += 1
                spike_positions_x[count] = x[ind[0]]
                spike_positions_y[count] = y[ind[0]]
                new_spike_times[count] = self.spike_times[index]

        spike_positions_x = spike_positions_x[:count + 1]
        spike_positions_y = spike_positions_y[:count + 1]
        new_spike_times = new_spike_times[:count + 1]

        return spike_positions_x.flatten(), spike_positions_y.flatten(), new_spike_times.flatten()


class HaftingOccupancyMap():
    def __init__(self, spatial_spike_train: SpatialSpikeTrain2D | Position2D, **kwargs):
        self.x = spatial_spike_train.x
        self.y = spatial_spike_train.y
        self.t = spatial_spike_train.t
        self.spatial_spike_train = spatial_spike_train
        self.arena_size = spatial_spike_train.arena_size

        self.map_data = None

        if 'session_metadata' in kwargs:
            self.session_metadata = kwargs['session_metadata']
        else:
            self.session_metadata = spatial_spike_train.session_metadata

        self.smoothing_factor = self.session_metadata.session_object.smoothing_factor

        if 'smoothing_factor' in kwargs:
            print('overriding session smoothing factor for input smoothing facator')
            self.smoothing_factor = kwargs['smoothing_factor']
        elif 'settings' in kwargs and 'smoothing_factor' in kwargs['settings']:
            self.smoothing_factor = kwargs['settings']['smoothing_factor']
            print('overriding session smoothing factor for input smoothing facator')

    def get_occupancy_map(self, smoothing_factor=None, new_size=None):
        if self.map_data is None or (self.map_data is not None and new_size != self.map_data.shape[0]) == True:
            if self.smoothing_factor != None:
                smoothing_factor = self.smoothing_factor
                assert smoothing_factor != None, 'Need to add smoothing factor to function inputs'
            else:
                self.smoothing_factor = smoothing_factor

            if new_size is not None:
                self.map_data, self.raw_map_data, self.coverage = self.compute_occupancy_map(self.t, self.x, self.y, self.arena_size, smoothing_factor, new_size=new_size)
            else:
                self.map_data, self.raw_map_data, self.coverage = self.compute_occupancy_map(self.t, self.x, self.y, self.arena_size, smoothing_factor)

            if isinstance(self.spatial_spike_train, SpatialSpikeTrain2D):
                self.spatial_spike_train.add_map_to_stats('occupancy', self)

        return self.map_data, self.raw_map_data, self.coverage

    def compute_occupancy_map(self, pos_t, pos_x, pos_y, arena_size, smoothing_factor, new_size=64, mask_threshold=1):

        # arena_ratio = arena_size[0]/arena_size[1]
        # h = smoothing_factor #smoothing factor in centimeters

        # if arena_ratio > 1: # if arena height (y) is bigger than width (x)
        #     x_vec = np.linspace(min(pos_x), max(pos_x), int(resolution))
        #     y_vec = np.linspace(min(pos_y), max(pos_y), int(resolution*arena_ratio))
        # if arena_ratio < 1: # if arena height is is less than width
        #     x_vec = np.linspace(min(pos_x), max(pos_x), int(resolution/arena_ratio))
        #     y_vec = np.linspace(min(pos_y), max(pos_y), int(resolution))
        # else: # if height == width
        #     x_vec = np.linspace(min(pos_x), max(pos_x), int(resolution))
        #     y_vec = np.linspace(min(pos_y), max(pos_y), int(resolution))

        # executor = mp.Pool() # change this to mp.cpu_count() if you want to use all cores
        # futures = list(executor.map(functools.partial(_pos_pdf, pos_x, pos_y, pos_t, smoothing_factor), ((x, y) for x, y in itertools.product(x_vec, y_vec))))
        # occupancy_map = np.array(futures).reshape(len(y_vec), len(x_vec))

        # mask_values = functools.partial(_mask_points_far_from_curve, mask_threshold, pos_x, pos_y)
        # mask_grid = np.array(list(executor.map(mask_values, itertools.product(x_vec, y_vec)))).reshape(len(y_vec), len(x_vec))

        # mask_grid = _interpolate_matrix(mask_grid, cv2_interpolation_method=cv2.INTER_NEAREST)
        # mask_grid = mask_grid.astype(bool)
        # occupancy_map = _interpolate_matrix(occupancy_map, cv2_interpolation_method=cv2.INTER_NEAREST)

        # # original, unparallelized code, in case parallelization is causing problems
        # #for xi, x in enumerate(x_vec):
        #     #for yi, y in enumerate(y_vec):
        #         #occupancy_map[yi,xi] = _pos_pdf((x, y))
        #         #mask points farther than 4 cm from the curve
        #         #mask_grid[yi,xi] = _distance_to_curve(point_x=x, point_y=y, curve_x=pos_x, curve_y=pos_y) > 4

        # valid_occupancy_map = np.ma.array(occupancy_map, mask=mask_grid)

        # valid_occupancy_map = np.rot90(valid_occupancy_map)



        valid_occupancy_map, raw_occ, coverage = _temp_occupancy_map(self.spatial_spike_train.position, self.smoothing_factor, interp_size=(new_size, new_size))

        return valid_occupancy_map, raw_occ, coverage


class HaftingSpikeMap():
    def __init__(self, spatial_spike_train: SpatialSpikeTrain2D, **kwargs):
        # self._input_dict = input_dict
        # self.spatial_spike_train = self._read_input_dict()
        self.spatial_spike_train = spatial_spike_train
        self.spike_x, self.spike_y, self.new_spike_times = self.spatial_spike_train.spike_x, self.spatial_spike_train.spike_y, self.spatial_spike_train.new_spike_times
        self.arena_size = self.spatial_spike_train.arena_size
        self.map_data = None

        if 'session_metadata' in kwargs:
            self.session_metadata = kwargs['session_metadata']
        else:
            self.session_metadata = spatial_spike_train.session_metadata

        self.smoothing_factor = self.session_metadata.session_object.smoothing_factor

        if 'smoothing_factor' in kwargs:
            print('overriding session smoothing factor for input smoothing facator')
            self.smoothing_factor = kwargs['smoothing_factor']
        elif 'settings' in kwargs and 'smoothing_factor' in kwargs['settings']:
            self.smoothing_factor = kwargs['settings']['smoothing_factor']
            print('overriding session smoothing factor for input smoothing facator')
    # def _read_input_dict(self):
    #     spatial_spike_train = None
    #     if 'spatial_spike_train' in self._input_dict:
    #         spatial_spike_train = self._input_dict['spatial_spike_train']
    #         assert isinstance(spatial_spike_train, SpatialSpikeTrain2D)
    #     return spatial_spike_train

    def get_spike_map(self, smoothing_factor=None, new_size=None):
        if self.map_data is None or (self.map_data is not None and new_size != self.map_data.shape[0]) == True:
            if self.smoothing_factor != None:
                smoothing_factor = self.smoothing_factor
                assert smoothing_factor != None, 'Need to add smoothing factor to function inputs'
            else:
                self.smoothing_factor = smoothing_factor
            
            if new_size is not None:
                self.map_data, self.map_data_raw = self.compute_spike_map(self.spike_x, self.spike_y, smoothing_factor, self.arena_size, new_size=new_size)
            else:
                self.map_data, self.map_data_raw = self.compute_spike_map(self.spike_x, self.spike_y, smoothing_factor, self.arena_size)

            self.spatial_spike_train.add_map_to_stats('spike', self)

        return self.map_data, self.map_data_raw

    def compute_spike_map(self, spike_x, spike_y, smoothing_factor, arena_size, new_size=64):
        # arena_ratio = arena_size[0]/arena_size[1]
        # # h = smoothing_factor #smoothing factor in centimeters

        # if arena_ratio > 1: # if arena height (y) is bigger than width (x)
        #     x_vec = np.linspace(min(spike_x), max(spike_x), int(resolution))
        #     y_vec = np.linspace(min(spike_y), max(spike_y), int(resolution*arena_ratio))
        # if arena_ratio < 1: # if arena height is is less than width
        #     x_vec = np.linspace(min(spike_x), max(spike_x), int(resolution/arena_ratio))
        #     y_vec = np.linspace(min(spike_y), max(spike_y), int(resolution))
        # else: # if height == width
        #     x_vec = np.linspace(min(spike_x), max(spike_x), int(resolution))
        #     y_vec = np.linspace(min(spike_y), max(spike_y), int(resolution))


        # if resolution >= 170: # This threshold was empirically determined on the development machine. Feel free to change it for other machines.
        #     # parallelized code for large resolution
        #     executor = mp.Pool(mp.cpu_count()) # change this to mp.cpu_count() if you want to use all cores
        #     futures = list(executor.map(functools.partial(_spike_pdf, spike_x, spike_y, smoothing_factor), ((x,y) for x, y in itertools.product(x_vec, y_vec))))
        #     spike_map = np.array(futures).reshape(len(y_vec), len(x_vec))

        # else:
        #     # non-parallel code is faster for smaller resolutions
        #     spike_map_vector = [_spike_pdf(spike_x, spike_y, smoothing_factor, (x,y)) for x,y in itertools.product(x_vec,y_vec)]
        #     spike_map = np.array(spike_map_vector).reshape(len(y_vec), len(x_vec))

        # spike_map = np.rot90(spike_map)

        # # Resize maps
        # spike_map = _interpolate_matrix(spike_map, cv2_interpolation_method=cv2.INTER_NEAREST)

        spike_map, spike_map_raw = _temp_spike_map(self.spatial_spike_train.x, self.spatial_spike_train.y, self.spatial_spike_train.t, arena_size, spike_x, spike_y, smoothing_factor, interp_size=(new_size,new_size))

        return spike_map, spike_map_raw

class HaftingRateMap():
    def __init__(self, spatial_spike_train: SpatialSpikeTrain2D, **kwargs):

        self.occ_map = spatial_spike_train.get_map('occupancy')
        if self.occ_map == None:
            self.occ_map = HaftingOccupancyMap(spatial_spike_train)
        self.spike_map = spatial_spike_train.get_map('spike')
        if self.spike_map == None:
            self.spike_map = HaftingSpikeMap(spatial_spike_train)
        self.spatial_spike_train = spatial_spike_train
        self.arena_size = spatial_spike_train.arena_size

        assert isinstance(self.occ_map, HaftingOccupancyMap)
        assert isinstance(self.spike_map, HaftingSpikeMap)

        self.map_data = None
        self.raw_map_data = None

        if 'session_metadata' in kwargs:
            self.session_metadata = kwargs['session_metadata']
        else:
            self.session_metadata = spatial_spike_train.session_metadata

        self.smoothing_factor = self.session_metadata.session_object.smoothing_factor

        if 'smoothing_factor' in kwargs:
            print('overriding session smoothing factor for input smoothing facator')
            self.smoothing_factor = kwargs['smoothing_factor']
        elif 'settings' in kwargs and 'smoothing_factor' in kwargs['settings']:
            self.smoothing_factor = kwargs['settings']['smoothing_factor']
            print('overriding session smoothing factor for input smoothing facator')

    def get_rate_map(self, smoothing_factor=None, new_size=None):
        if self.map_data is None or (self.map_data is not None and new_size != self.map_data.shape[0]) == True:
            if self.smoothing_factor == None:
                self.smoothing_factor = smoothing_factor
                assert smoothing_factor != None, 'Need to add smoothing factor to function inputs'

            if new_size is not None:
                self.map_data, self.raw_map_data = self.compute_rate_map(self.occ_map, self.spike_map, new_size=new_size)
            else:
                self.map_data, self.raw_map_data = self.compute_rate_map(self.occ_map, self.spike_map)

            self.spatial_spike_train.add_map_to_stats('rate', self)
        # elif self.map_data is not None and new_size != self.map_data.shape[0]:

        return self.map_data, self.raw_map_data

    def compute_rate_map(self, occupancy_map, spike_map, new_size=None):
        '''
        Parameters:
            spike_x: the x-coordinates of the spike events
            spike_y: the y-coordinates of the spike events
            pos_x: the x-coordinates of the position events
            pos_y: the y-coordinates of the position events
            pos_time: the time of the position events
            smoothing_factor: the shared smoothing factor of the occupancy map and the spike map
            arena_size: the size of the arena
        Returns:
            rate_map: spike density divided by occupancy density
        '''

        if new_size is None:
            if self.smoothing_factor != None:
                occ_map_data, raw_occ, coverage = occupancy_map.get_occupancy_map(self.smoothing_factor)
                spike_map_data, spike_map_data_raw = spike_map.get_spike_map(self.smoothing_factor)
            else:
                print('No smoothing factor provided, proceeding with value of 3')
                occ_map_data, raw_occ, coverage = occupancy_map.get_occupancy_map(3)
                spike_map_data, spike_map_data_raw = spike_map.get_spike_map(3)
        else:
            if self.smoothing_factor != None:
                occ_map_data, raw_occ, coverage = occupancy_map.get_occupancy_map(self.smoothing_factor, new_size=new_size)
                spike_map_data, spike_map_data_raw = spike_map.get_spike_map(self.smoothing_factor, new_size=new_size)
            else:
                print('No smoothing factor provided, proceeding with value of 3')
                occ_map_data, raw_occ, coverage = occupancy_map.get_occupancy_map(3, new_size=new_size)
                spike_map_data, spike_map_data_raw = spike_map.get_spike_map(3, new_size=new_size)


        assert occ_map_data.shape == spike_map_data.shape

        rate_map_raw = np.where(raw_occ<0.0001, 0, spike_map_data_raw/raw_occ)
        rate_map = np.where(occ_map_data<0.0001, 0, spike_map_data/occ_map_data)
        rate_map = rate_map/max(rate_map.flatten())

        # rate_map_raw = _compute_unmasked_ratemap(occ_map_data, spike_map_data)

        # rate_map = np.ma.array(rate_map_raw, mask=coverage)
        # rate_map = np.ma.array(rate_map_raw, mask=raw_occ)
        # rate_map = np.ma.array(rate_map, mask=occ_map_data)

        return rate_map, rate_map_raw




        # def shuffle_spike_positions(self, displacement):
        #     pass

    # def make_rate_map(self):
    #     HaftingRateMap(self)

    # def make_occupancy_map(self):
    #     HaftingOccupancyMap(self)

    # def make_spike_map(self):
    #     HaftingSpikeMap(self)


