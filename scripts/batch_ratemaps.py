import os
import sys

PROJECT_PATH = os.getcwd()
sys.path.append(PROJECT_PATH)
print(PROJECT_PATH)

from core.data_study import Study, Animal

from library.maps import get_rate_map
from library.spatial.get_spike_pos import get_spike_pos
from prototypes.wave_form_sorter.sort_cell_spike_times import sort_cell_spike_times

def batch_rate_maps(study: Study):
    animals = study.animals

    for animal in animals:

        cells, waveforms = sort_cell_spike_times(animal.agg_spike_times, animal.agg_cluster_labels, animal.agg_waveforms)

        animal.add_sorted_data(cells, waveforms)
        
        c = 0
        for session in animal.session_keys:

            pos_x = animal.stat_dict[session]['pos_x']
            pos_y = animal.stat_dict[session]['pos_y']
            pos_t = animal.stat_dict[session]['pos_t']
            arena_size = animal.stat_dict[session]['arena_size']

            smoothing_factor = 5
            # Kernel size
            kernlen = int(smoothing_factor*8)
            # Standard deviation size
            std = int(0.2*kernlen)

            k = 0
            for cell in animal.agg_cell_keys:

                spikex, spikey = get_spike_pos(cells[c,k], pos_x, pos_y, pos_t)

                ratemap_smooth, ratemap_raw = get_rate_map(pos_x, pos_y, pos_t, arena_size, spikex, spikey, kernlen, std)

                cell_stat = {
                    'ratemap_smooth': ratemap_smooth,
                    'ratemap_raw': ratemap_raw,
                }

                animal.add_single_cell_stat(session, cell, cell_stat)
                k += 1
            
            c += 1


              

           





