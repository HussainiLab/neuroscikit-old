import os, sys

PROJECT_PATH = os.getcwd()
sys.path.append(PROJECT_PATH)



from core.data_study import (
    Animal,
    Study
)

from _prototypes.wave_form_sorter.sort_cell_spike_times import sort_cell_spike_times
from _prototypes.wave_form_sorter.neuron_waveform_template import waveform_template
from _prototypes.wave_form_sorter.get_peak_amplitudes import get_peak_amplitudes
from _prototypes.wave_form_sorter.get_spike_statistics import get_spike_statistics
from _prototypes.wave_form_sorter.get_possible_orders import get_possible_orders

def sort_waveforms_by_session(animal: Animal, study: Study):
    """
    Sort waveforms by session
    """
    cells, sorted_waveforms = sort_cell_spike_times(animal.agg_spike_times, animal.agg_cluster_labels, animal.agg_waveforms)

    average_waveforms, _, _ = waveform_template(sorted_waveforms)

    agg_waveform_dict = {}
    for i in range(len(sorted_waveforms)):
        session_key = 'session_' + str(i+1)
        agg_waveform_dict[session_key] = {}
        for j in range(len(sorted_waveforms[i])):
            waveform_dict = get_spike_statistics(sorted_waveforms[i][j], study.sample_rate)
            orders = get_possible_orders(waveform_dict['pp_amp'], threshold=0.2) #what is pp_amp? Peak amplitude?
            waveform_dict['channel_orders'] = orders
            cell_key = 'cell_' + str(j+1)
            agg_waveform_dict[session_key][cell_key] = waveform_dict

    return agg_waveform_dict