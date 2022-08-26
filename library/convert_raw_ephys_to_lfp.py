"""This module is for converting raw electrophysiology data to local field potential (LFP) data. Essentially, these are tools for filtering and downsampling electrophysiology data.
"""

import numpy as np

def down_sample_ephys(ephys_data, sampling_rate, new_sampling_rate):
    """Downsample the electrophysiology data.

    Parameters:
        ephys: the a 1D iterable object containing the electrophysiology data to be downsampled.
        sampling_rate: the sampling rate of the electrophysiology data in Hz.
        new_sampling_rate: the new sampling rate of the electrophysiology data.
    Returns:
        The downsampled electrophysiology data.
    """
    # compute the duration in seconds
    # (if given Hz sampling rate)
    duration = float(len(ephys_data) / sampling_rate)

    # compute the idealized step size for a
    # continous recording sampled at a lower
    # rate
    continuous_step_size = float(new_sampling_rate / sampling_rate)

    # compute the idealized continous time index
    # for each sample in the original data
    continuous_index = np.arange(0, duration, smooth_step_size)

    # round the idealized index to get the discrete
    # index for each sample in the original data
    discrete_index = [round(i) for i in smooth_index]

    # take the data points at the discrete index
    ephys_downsampled = ephys[discrete_index]

    return ephys_downsampled