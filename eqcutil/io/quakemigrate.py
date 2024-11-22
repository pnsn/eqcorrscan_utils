"""
:module: eqcorrscan_utils.quakemigrate
:auth: Nathan T. Stevens
:email: ntsteven@uw.edu
:org: Pacific Northwest Seismic Network
:license: GNU GPLv3
:purpose: Provides support for converting *.event and *.pick CSV
    outputs from QuakeMigrate into an ObsPy :class:`~obspy.core.event.Event` objects

:AI Attribution: This module was prototyped using prompts with ChatGPT and then
    tested and verified for functionality by the author
"""
import os, logging, warnings

import pandas as pd
from obspy import UTCDateTime
from obspy.core.event import Catalog, Event, Origin, Arrival, Pick, ResourceIdentifier
from obspy.core.event import OriginUncertainty, WaveformStreamID, Magnitude, QuantityError, CreationInfo


Logger = logging.getLogger(__name__)

EVENT_FILE_COLS = [
    "EventID",
    "DT",
    "X",
    "Y",
    "Z",
    "COA",
    "COA_NORM",
    "GAU_X",
    "GAU_Y",
    "GAU_Z",
    "GAU_ErrX",
    "GAU_ErrY",
    "GAU_ErrZ",
    "COV_ErrX",
    "COV_ErrY",
    "COV_ErrZ",
    "TRIG_COA",
    "DEC_COA",
    "DEC_COA_NORM",
]

PICK_FILE_COLS = [
    "Station",
    "Phase",
    "ModelledTime",
    "PickTime",
    "PickError",
    "SNR"
]

# TODO: Make a stream formatter that accepts and Inventory as an input

def stream_id_formatter(phase, station, network='UW', location='', chan_mapping={'P':'HHZ','S':'HHN'}):
    """Given the Phase and Station values from a row in a *.pick file,
    reconstitute a SEED channel ID string

    :param phase: phase name
    :type phase: str
    :param station: station name
    :type station: str
    :param network: default network code, defaults to 'UW'
    :type network: str, optional
    :param location: default location code, defaults to ''
    :type location: str, optional
    :param chan_mapping: phase to channel code mapping, defaults to {'P':'HHZ','S':'HHN'}
    :type chan_mapping: dict, optional
    :return: SEED channel ID
    :rtype: str
    """    
    if phase not in chan_mapping.keys():
        raise KeyError('Phase value not found in chan_mapping keys')
    if phase not in ['P','S']:
        raise ValueError('Phase must be either "P" or "S"')
    if chan_mapping.keys() != set(['P','S']):
        raise KeyError('chan_mapping keys must be "P" and "S"')
    if not isinstance(station, (str, int)):
        raise ValueError('station must be type str or int')
    if not isinstance(location, str):
        raise ValueError('location must be type str')
    return '%s.%s.%s.%s'%(network, station, location, chan_mapping[phase])

def resource_id_formatter(format='quakeml', source='local', method='quakemigrate', resource_type='event', extras=None, resource_name=None):
    """Convenience method wrapping :class:`~obspy.core.event.resourceid.ResourceIdentifier`

    Provides fields and defaults for formatting

    :param format: Identifier format, defaults to 'quakeml'
        Supports: 'quakeml' and 'smi'
    :type format: str, optional
    :param source: name of where the metadata came from, defaults to 'local'
        'local' is a catch-all for stuff you ran on your computer
    :type source: str, optional
    :param method: what method/software was used to generate these metadata,
        defaults to 'quakemigrage'
    :type method: str, optional
    :param resource_type: type of metadata, defaults to 'event'
        Expected values: event, origin, pick, arrival, magnitude
    :type resource_type: str, optional
    :param resource_name: unique identifier for this resource, defaults to None
        None - allows ResourceIdentifier to assign a unique hash-key using the
         **prefix** input argument to ResourceIdentifier
        str or int - string or integer to use as the unique (string formatted)
            resource ID
    :type resource_name: None, str, int, optional
    :return: resource_id object
    :rtype: obspy.core.event.resourceid.ResourceIdentifier
    """    
    # input compatability checks
    if format not in ['quakeml','smi']:
        raise ValueError(f'format "{format}" not supported')
    if not isinstance(source, str):
        raise TypeError
    if not isinstance(method, str):
        raise TypeError
    if not isinstance(resource_type, str):
        raise TypeError
    elif resource_type not in ['event','origin','pick','arrival','magnitude']:
        warnings.warn(f'resource_type "{resource_type}" is non-standard')

    # Create prefix
    prefix = f'{format}:{source}/{method}/{resource_type}'
    if isinstance(extras, str):
        prefix = f'{prefix}/{extras}'
    elif hasattr(extras, '__iter__'):
        if all(isinstance(_e, str) for _e in extras):
            for _e in extras:
                prefix = f'{prefix}/{_e}'
    elif extras is None:
        pass
    else:
        raise ValueError('extras must be str, an iterable collection of str, or NoneType')

    # If resource_name is provided, pass as **id** to ResourceID
    if isinstance(resource_name, (str,int)):
        rid=ResourceIdentifier(id=f'{prefix}/{resource_name}')
    # If resource_name is None, use **prefix** 
    elif resource_name is None:
        rid=ResourceIdentifier(prefix=prefix)
    # Otherwise, raise error
    else:
        raise TypeError('resource_name must be type int, str, or NoneType')
    # Return ResourceIdentifier object
    return rid

def  quakemigrate2cat(event_files, pick_files, hyp_type='max', min_snr=3,
                      network='XX', location='', chan_mapping={'P': 'HHZ','S':'HHN'},
                      qml_extras=None):
    """Convert the output *.event and *.pick files from a QuakeMigrate
    run into an ObsPy :class:`~obspy.core.event.Catalog` object that
    has the necessary pick/arrival referencing and phase name / hint
    metadata structure to directly work with EQcorrscan functions.
    E.g., :meth:`~eqcorrscan.core.match_filter.tribe.Tribe.construct`


    :param event_files: name(s) of *.event file from QuakeMigrate to convert
    :type event_files: list or str
    :param pick_file: name(s) of *.pick file from QuakeMigrate to convert
    :type pick_file: list or str
    :param hyp_type: hypocentral parameter estimate type to use, defaults to 'max'.
        Supported Values:
         - 'max' -- uses the X,Y,Z values for longitude, latitude, and depth, respectively
         - 'gau' -- uses GAU_X, GAU_Y, GAU_Z values for hypocentral parameters
    :type hyp_type: str, optional.
    :param min_snr: minimum Signal to Noise Ratio to allow for QuakeMigrate picks (column SNR),
        defaults to 3
    :type min_snr: scalar, optional.
    :param network: network code to assign to all picks to make a SEED channel name code,
        defaults to 'XX'
    :type network: str, optional
    :param location: location code to assign to all picks to make a SEED channel name code,
         defaults to ''
    :type location: str, optional
    :param chan_mapping: phase name to SEED channel code mapping, defaults to {'P': 'HHZ', 'S':'HHN'},
    :type chan_mapping: dict, optional
    
    :return: catalog-formatted event metadata
    :rtype: obspy.core.event.Catalog
    
    FOOTNOTE: 
    
    This script is a work-in-progress and requires some additional
    modifications to correctly document the source uncertainties output
    by QuakeMigrate, that constitute a covariance matrix in the orthogonal
    basis of the velocity model used. Additionally, more metadata regarding
    the prescribed earth model could be added. These items are not strictly
    needed if the user simply wants to convert the QM outputs into a "bare-minimum"
    catalog 

    TODO: eventually allow an obspy.core.inventory.Inventory object input
    for the SEED channel naming function
    """    

    # Compatability check for event_file
    df_e = pd.DataFrame()
    if isinstance(event_files, str):
        event_files = [event_files]
    if isinstance(event_files, list):
        for _e in event_files:
            if os.path.isfile(_e):
                idf = pd.read_csv(_e)
                if set(EVENT_FILE_COLS) <= set(idf.columns):
                    df_e = pd.concat([df_e, idf], ignore_index=True)
                else:
                    Logger.warning(f'event_file {_e} does not appear to have the correct column names')
            else:
                Logger.warning(f'event_file {_e} was not found')
    else:
        Logger.critical(f'event_files type {type(event_files)} not supported. Must be str or list of str')
    
    df_p = pd.DataFrame()
    if isinstance(pick_files, str):
        pick_files = [pick_files]
    if isinstance(pick_files, list):
        for _e in pick_files:
            if os.path.isfile(_e):
                idf = pd.read_csv(_e)
                evid = os.path.split(_e)[-1]
                evid = os.path.splitext(evid)[0]
                idf = idf.assign(EventID=[int(evid) for _e in range(len(idf))])
                if set(PICK_FILE_COLS) <= set(idf.columns):
                    df_p = pd.concat([df_p, idf], ignore_index=True)
                else:
                    Logger.warning(f'pick_file {_e} does not appear to have the correct column names')
            else:
                Logger.warning(f'pick_file {_e} was not found')
    else:
        Logger.critical(f'pick_files type {type(pick_files)} not supported. Must be str or list of str')    
    
    # Check if any of the events have local magnitude estimates
    if 'ML' in df_e.columns:
        hasmag = True
    else:
        hasmag = False

    # Sanity check to only take picks that match the given Event_ID
    df_p = df_p[df_p.EventID.isin(df_e.EventID)]
    if len(df_p) == 0:
        Logger.critical('No phases matched event_id values in "event_file"')
    else:
        Logger.info(f'Matched {len(df_p)} picks to {len(df_e)} events')

    ## START MAKING THE CATALOG ##
    cat = Catalog()
    for _, erow in df_e.iterrows():
        # Subset Picks to Match current EVID
        Logger.info(f'Processing event_id: {erow.EventID}')
        idf_picks = df_p[df_p.EventID == erow.EventID]
        Logger.info(f'...with {len(idf_picks)} picks')
        # Create event
        event = Event(resource_id = resource_id_formatter(extras=qml_extras, resource_name=erow.EventID))
        # Create Origin
        origin = Origin(resource_id = resource_id_formatter(extras=qml_extras, resource_type='origin'))

        # Populate best-estimate hypocenter
        origin.time = UTCDateTime(erow.DT)
        if hyp_type.lower() == 'max':
            origin.latitude = erow.Y
            origin.longitude = erow.X
            origin.depth = erow.Z
        # Or populate with gaussian hypocenter
        elif hyp_type.lower() == 'gau': 
            origin.latitude = erow.GAU_Y
            origin.longitude = erow.GAU_X
            origin.depth = erow.GAU_Z


        # TODO: Add uncertainties (need to do coordinate conversions)

        # Append origin to event
        event.origins.append(origin)
        # Set as preferred origin ID
        event.preferred_origin_id = origin.resource_id

        if hasmag:
            if isinstance(erow.ML, (int, float)):   
                Logger.info(f'EVID: {erow.EventID} has magnitude estimate - including in Event description')
                magnitude = Magnitude(
                    resource_id=resource_id_formatter(extras=qml_extras, resource_type='magnitude'),
                    mag=erow.ML,
                    magnitude_type='ML',
                    mag_errors=QuantityError(uncertainty=erow.ML_Err),
                    origin_id = origin.resource_id
                                    )
                # Append magnitude to event
                event.magnitudes.append(magnitude)
                # Set as preferred magnitude ID
                event.preferred_magnitude_id = magnitude.resource_id
            else:
                Logger.info(f'EVID: {erow.EventID} did not have magnitude estimate - skipping magnitude object generation')

        # Populate Picks and Arrivals
        for _, prow in idf_picks.iterrows():
            # Create pick
            if prow.SNR >= min_snr:
                seed_id = stream_id_formatter(prow.Phase, prow.Station, network=network, location=location, chan_mapping=chan_mapping)
                pick = Pick(
                    resource_id=resource_id_formatter(extras=qml_extras, resource_type='pick'),
                    time = UTCDateTime(prow.PickTime),
                    time_errors = prow.PickError,
                    waveform_id = WaveformStreamID(seed_string=seed_id),
                    evaluation_mode = 'automatic',
                    phase_hint=prow.Phase)
                # Create arrival that references pick and has travel time uncertainty
                arrival = Arrival(
                    resource_id=resource_id_formatter(extras=qml_extras, resource_type='arrival'),
                    pick_id = pick.resource_id,
                    phase=prow.Phase,
                    time_residual=UTCDateTime(prow.PickTime) - UTCDateTime(prow.ModelledTime))
                # Append pick to event
                event.picks.append(pick)
                # Append arrival to preferred origin
                event.preferred_origin().arrivals.append(arrival)
            else:
                continue
        # Append event to catalog
        cat.events.append(event)
    # Return catalog
    return cat

def _qm2cat_inner_process(df_e, df_p, hyp_type='max', min_snr=3, network='', location='', chan_mapping={'P':'HHZ','S':'HHN'}):
    """PRIVATE METHOD

    Inner method for converting pre-read & format checked
    event and pick dataframes from QuakeMigrate outputs
    into an obspy Catalog object

    :param df_e: event dataframe
    :type df_e: pandas.DataFrame
    :param df_p: pick dataframe
    :type df_p: pandas.DataFrame
    :param hyp_type: type of hypocentral solution estimate to use, 
        defaults to 'max'
        Supported Values:
        - 'max': uses X, Y, Z from *.event
        - 'gau': uses GAU_X, GAU_Y, GAU_Z from *.event
    :type hyp_type: str, optional
    :return: catalog object
    :rtype: obspy.core.event.Catalog
    """    
    if not isinstance(df_e, pd.DataFrame):
        Logger.critical('df_e must be type pandas.DataFrame')
    if not isinstance(df_p, pd.DataFrame):
        Logger.critical('df_p must be type pandas.DataFrame')

    if hyp_type.lower() not in ['max','gau']:
        Logger.critical(f'hyp_type {hyp_type} not supported.')

    
    return cat

        