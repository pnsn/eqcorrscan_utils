"""
:module: eqcorrscan_utils.waveforms
:auth: Nathan T. Stevens
:email: ntsteven@uw.edu
:org: Pacific Northwest Seismic Network
:license: GPLv3
:purpose:
    This module provides some helper functions
    to aid in initializing and using ObsPlus
    :class:`~obsplus.bank.wavebank.WaveBank` objects
    see: https://github.com/niosh-mining/obsplus
"""

import os, glob
from pathlib import Path
from obspy import read
from obsplus import WaveBank

def initialize_wavebank(mseed_files=[],
                        base_path=os.path.join('.','WaveBank'),
                        path_structure='{year}',
                        name_structure='{seedid}.{time}',
                        **kwargs):
    """Helper script for initializing a :class:`~obsplus.bank.wavebank.WaveBank`
    on a local machine and loading in a list of mimiseed files

    see :class:`~obsplus.bank.wavebank.WaveBank` for further
    details on parameter values and options

    :param mseed_files: list of miniSEED (or other ObsPy read-able files)
        to load into a new WaveBank, defaults to []
    :type mseed_files: list, optional
    :param base_path: root directory to house the WaveBank,
        creating the necessary directory structure if it does
        not already exist, defaults to os.path.join('.','WaveBank')
    :type base_path: str, optional
    :param path_structure: internal directory structure for the
        WaveBank to populate, defaults to '{year}'
    :type path_structure: str, optional
    :param name_structure: file naming format for waveform files
        populated within the WaveBank , defaults to '{seedid}.{time}'
    :type name_structure: str, optional
    :return: wbank - established wavebank client
    :rtype: obsplus.bank.wavebank.WaveBank
    """
    if not os.path.exists(base_path):
        os.makedirs(base_path)

    wbank = WaveBank(base_path=base_path,
                     path_structure=path_structure,
                     name_structure=name_structure,
                     **kwargs)
    
    for msfile in mseed_files:
        st = read(msfile)
        wbank.put_waveforms(st)
    return wbank


def connect_to_wavebank(base_path=os.path.join('.','WaveBank'),
                        path_structure='{year}',
                        name_structure='{seedid}.{time}',
                        **kwargs):
    """Convenience method for connecting to an initialized
    WaveBank generated by :meth:`~eqcorrscan_utils.methods.obsplus.initialize_wavebank`

    :param base_path: base path to the wavebank root directory, defaults to './WaveBank'
    :type base_path: str, optional
    :param path_structure: internal directory structure for the wavebank, defaults to '{year}'
    :type path_structure: str, optional
    :param name_structure: file naming structure for the wavebank, defaults to '{seedid}.{time}'
    :type name_structure: str, optional
    :return: wbank - established wavebank client
    :rtype: obsplus.bank.wavebank.WaveBank
    """    
    wbank = WaveBank(base_path=base_path,
                     path_structure=path_structure,
                     name_structure=name_structure,
                     **kwargs)
    return wbank