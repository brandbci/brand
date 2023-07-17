# Guidelines for Writing BRAND Nodes for NWB Compatibility

This guide will detail best practices for writing BRAND nodes to be compatible with general NWB exporting. Doing so requires the node's author to be familiar with the NWB data structure. Useful links can be found here:

* [Neurodata Without Borders website](https://www.nwb.org/)
* [PyNWB Documentation](https://pynwb.readthedocs.io/en/latest/index.html)
* [MatNWB Documentation](https://neurodatawithoutborders.github.io/matnwb/doc/index.html)

## Graph YAML

Configuration for the `exportNWB.py` script is included in the graph YAML, within the `derivatives` field.

```yaml
derivatives:
  - exportNWB:
      parameters:
        participant_file:       ../Data/t0/t0.yaml
        description:            description of the graph
        sync_key:               <the sync key used throughout the graph>
        time_key:               <the time key used throughout the graph>
        streams:
          <graph_stream_1>:                                 # stream name as defined in the graph

            source_node:        <name of source node>       # name of the node with the corresponding YAML file from 
                                                            # which stream config will be read for NWB export   
            
            enable:             <True/False>                # optional, defaults to the node's YAML value if not
                                                            # defined here

            sync:               <list of sync labels>       # the 0th item should be the blocking sync, add others to
                                                            # include in NWB

            name:               <stream name in node YAML>  # the name of the stream in the node's YAML corresponding
                                                            # to this stream in the graph

            <graph_key_1>:      <node_key_1>                # the name of the key in the stream in the node's YAML
                                                            # corresponding to the key in the stream in the graph

            <graph_key_2>:      <node_key_2>                # the name of the key in the stream in the node's YAML
                                                            # corresponding to the key in the stream in the graph

          <graph_stream_2>:                                 # stream name as defined in the graph

            source_node:        <name of source node>       # name of the node with the corresponding YAML file from 
                                                            # which stream config will be read for NWB export  

            enable:             <True/False>                # optional, defaults to the node's YAML value if not
                                                            # defined here

            sync:               <list of sync labels>       # the 0th item should be the blocking sync, add others to
                                                            # include in NWB

            name:               <stream name in node YAML>  # the name of the stream in the node's YAML corresponding
                                                            # to this stream in the graph

            <graph_key_1>:      <node_key_1>                # the name of the key in the stream in the node's YAML
                                                            # corresponding to the key in the stream in the graph

            <graph_key_2>:      <node_key_2>                # the name of the key in the stream in the node's YAML
                                                            # corresponding to the key in the stream in the graph
```

Here is an example `exportNWB` configuration:

```yaml
derivatives:
- exportNWB:
    parameters:
      participant_file:   ../Data/t0/t0.yaml
      description:        testing FSM for individuated finger movements
      sync_key:           sync
      time_key:           ts
      streams:
        state:
          source_node:    my_cool_node
          enable:         True
          sync:           ['xPC_clock']
          name:           state
          state:          state
        trial_success:
          source_node:    my_cool_node
          # no enable, so uses the default from the node's YAML
          sync:           ['xPC_clock']
          name:           trial_success
          success:        success
```

Placing the `sync_key`, `time_key`, and `sync` options at the graph level provides flexibility to change graph connections without altering stream structures in a node's YAML. Coupling graph streams to node stream definitions with the `name` parameter and coupling the keys in a graph stream to keys in a node stream definition also support flexibility in changing graph connections without altering node YAMLs. This implementation allows an arbitrary stream to be connected to an arbitrary node's input (provided the structure matches) while maintaining support for logging with NWB. Lastly, using the `source_node` parameter indicates the name (not nickname) of the node that generates the stream, allowing the node's YAML file containing the configuration to be found.

As described below, the YAML file of the node that generates a stream will also contain an `enable_nwb` parameter for whether that stream is enabled for logging by default. The `enable_nwb` parameter in the `exportNWB.py` derivative configuration in the graph YAML is the priority setting for a given stream. If the `enable` key is not included under a stream's parameters within the `exportNWB.py` derivative configuration, then `exportNWB.py` pulls the parameter from the node's YAML.

As will be mentioned below, `exportNWB.py` also requires a YAML file with data on the participant. The path to this file is also specified in the `exportNWB.py` parameters, within the `participant_file` field.

## Data Alignment

Since BRAND runs asynchronous graphs, there is a need to track the flow of data through a graph for data integrity. See the [Guidelines for Data Alignment](https://github.com/snel-repo/realtime_rig_dev/blob/dev/doc/DataSyncGuidelines.md) for a description of how this is implemented for `exportNWB.py`. This is therefore critical to the functionality of `exportNWB.py`, since it must take that data and store it in a deterministic way. To do so, data from all streams in a graph are logged using the `sync` key contained in each stream entry as the timestamp for that entry. `exportNWB.py` also generates a `<stream_name>_sync` container that uses the NWB `TimeSeries` container. The `<stream_name>_sync` `TimeSeries` has one item entered for each `sync` key value in the stream. In each item, `exportNWB.py` logs the `monotonic` timestamps, which are required according to the [Guidelines for Data Alignment](https://github.com/snel-repo/realtime_rig_dev/blob/dev/doc/DataSyncGuidelines.md), and Redis timestamps at which each entry was logged. Additionally, if the stream is composed of multiple input streams, any additional `sync` labels are included in a separate column of `<stream_name>_sync`.

## Node YAML

Information regarding how a stream should be exported in an NWB file should be contained in the YAML file for the node that generates that stream. This implies the author of the node must write information regarding how that stream should be logged in NWB, as the author knows the stream's content best. Within a node's YAML, the NWB writing information is included in the stream's definition:

```yaml
RedisStreams:
  Inputs:
    ...

  Outputs:
    <output_stream_1>:
      enable_nwb:             <True/False>
      type_nwb:               <TimeSeries/Position/SpikeTimes/Trial/TrialInfo>
      <output_stream_1_key_1>:
        chan_per_stream:      [number of channels in each stream entry]
        samp_per_stream:      [number of samples per channel in each stream entry]
        sample_type:          [datatype of the sample]
        nwb:
          <nwb_parameter_1>:  value
          <nwb_parameter_2>:  value
          ...
      <output_stream_1_key_2>:
        ...
    <output_stream_2>:
      ...
```

Datatypes supported by `exportNWB.py` include any numeric datatype inherently supported by `numpy`, and strings. In the stream's definition in the node YAML, strings must have the datatype `str` to be logged in the NWB file without crashing the script.

`enable_nwb` is a required parameter that represents the default behavior for whether the stream `output_stream_1` should be exported to NWB if the `enable_nwb` parameter is not defined for `output_stream_1` at the graph level, which is the priority value. `type_nwb` is a required parameter that represents what NWB mechanism (see Rules below) should be used to fit all the data of the stream. Within each stream's keys, one can enable logging of that key by including an `nwb:` parameter field even if no parameters are required. Omitting the `nwb:` parameter field disables that key from being logged. Current supported mechanisms are `TimeSeries`, `Position`, `SpikeTimes`, `Trial`, and `TrialInfo`. See sections below for required `nwb` parameters for each mechanism.

### Rules for NWB Logging Mechanisms

Please follow each mechanism's rules to guarantee your data is properly logged in the NWB file.

#### `TimeSeries`

The `TimeSeries` mechanism creates a `TimeSeries` NWB container with data stored as a generic time series. This is equivalent to storing a `numpy.ndarray` of size `[num_time, num_dimensions]`. `exportNWB.py` logs sample times using the `sync` key included in the entry (see DataSyncGuidelines.md). Required `nwb` parameters in the stream's definition are those required for a [`TimeSeries`](https://pynwb.readthedocs.io/en/stable/pynwb.behavior.html#pynwb.behavior.TimeSeries) object in the NWB format, namely:

* `unit`: (`str`) the base unit of measurement (should be SI unit)

Note: `name`, `data`, and one of `timestamps` or `rate` are required, but these are generated automatically by `exportNWB.py`.

#### `Position`

The `Position` mechanism creates a `Position` NWB container with data stored as a time series. This is equivalent to storing a `numpy.ndarray` of size `[num_time, num_dimensions]`. `exportNWB.py` logs sample times using the `sync` key included in the entry (see DataSyncGuidelines.md). Required `nwb` parameters in the stream's definition are those required for a [`SpatialSeries`](https://pynwb.readthedocs.io/en/stable/pynwb.behavior.html#pynwb.behavior.SpatialSeries) object in the NWB format, namely:

* `reference_frame`: (`str`) description defining what the zero-position is

Note: `name`, `data`, and one of `timestamps` or `rate` are required, but these are generated automatically by `exportNWB.py`.

#### `Spike_Times`

The `Spike_Times` mechanism adds new units to the `units` table in the NWB file containing the spiking times of the electrode. Each stream entry should be of the format `[1, num_electrodes]` where each element is a boolean indicator of a spike having occurred on that channel for that entry. Spiking times logged in the `units` table are the `sync` key values at which the entries were added to the stream. The only required `nwb` parameter is:

* `crossings`: (`str`) not a formal NWB parameter, but indicates to `exportNWB.py` which key in the stream's entries contains the threshold crossing indicators.

#### `Trial`

The `Trial` mechanism creates a `trials` table in the NWB file. Each entry in the `trials` table must have start and stop times. The `trials` table forces no structure on continuously acquired data (such as data stored via the `Position` mechanism). Customized variables can be added to this table, i.e. movement onset times (see `other_trial_indicators` below). If a custom variable does not have a value for a given trial, that table entry is automatically filled with `NaN` (i.e. consider a monkey that fails a trial yielding no reward, so the reward time would be `NaN`). **At most one** stream in the entire graph should have its `type_nwb` set to `Trial`, and `exportNWB.py` automatically processes the `Trial` stream first if one is enabled (see `Trial_Info` for reasoning). An `indicators` column is automatically generated in the `trials` table to indicate which `start` and `end` trial indicators resulted in each trial. Required `nwb` parameters for the `Trial` mechanism are as follows:

* `trial_state`: (`str`) not a formal NWB parameter, but the name of the stream key containing trial states.
* `start_trial_indicators`: (`list` of (`str` or `numeric`)) not a formal NWB parameter, but elements indicating the start of a trial. For example, this could be a list such as `['start_trial']` where presence of this string indicates the time at which a trial was started. Note, `numeric` elements in the list have not been tested.
* `end_trial_indicators`: (`list` of (`str` or `numeric`)) not a formal NWB parameter, but elements indicating the end of a trial. For example, this could be a list such as `['stop_trial']` or with more abstract trial states, such as `['failure', 'between_trials']`, where presence of these strings indicate the time at which a trial was concluded. Note, `numeric` elements in the list have not been tested.
* `other_trial_indicators`: (`list` of (`str` or `numeric`)) not a formal NWB parameter, but elements indicating significant trial milestones. For example, this could be a list such as `['movement', 'reward']`. This parameter is required, though it can be an empty list indicated as `[]`.

Optional `nwb` parameters for the `Trial` mechanism are as follows:

* `<other_indicator>_description`: (`str`) descriptions of trial columns are required in the NWB file format. Every element of `other_trial_indicators` must have its own description parameter under `nwb` and the parameter name must match the exact name as included in `other_trial_indicators` with `_description` appended to the end.

#### `Trial_Info`

The `Trial_Info` mechanism adds trial information as columns to the `trials` table. The `Trial_Info` mechanism requires a pre-existing `trials` table, so `exportNWB.py` automatically processes the *only* `Trial` stream first. The data from each key in a `Trial_Info` stream is logged as a separate trial column. The column name in the `trials` table is autogenerated to be `<stream_name>_<key_name>`. If multiple data samples exist in a key for a given trial, only the first sample belonging to the trial is logged in the table. Note that data samples for a trial may be a vector of samples from multiple channels, where the whole vector will be logged as the entry for the trial. If no data points exist in a key for a given trial, the table entry is filled with a `NaN`. The only required `nwb` parameter is:

* `description`: (`str`) description of the trial column to be added, which is required in the NWB file format.

## Participant Metadata

It is helpful to log de-identified participant information alongside data without having to manually enter it into each NWB file. To this end, a `<participant>.yaml` (i.e. named `T14.yaml`), containing de-identified participant metadata, is required to store data in an NWB file using `exportNWB.py`. Atemplate for this file is included at `derivatives/exportNWB/templates/t0.yaml`.

The `<participant>.yaml` file should be structured as follows, and all elements are required:

```
metadata:
  participant_id:         T<num>
  cortical_implant_date:  [date of cortical implant surgery]

implants:
  - name:       [name of implant, i.e. medial hand knob]
    location:   [anatomical location of implant]
    position:   [stereotaxic position of implant]
    device:     [name of device, i.e. NeuroPort10x10]
    connector:  [name of connector, i.e. left anterior]
    serial:     [serial number of the device]
    array_map:  [path to the map file of the device provided by manufacturer]
  
  - name:       
    ...
```

To store electrophysiology recordings in the NWB file format, information about the devices used for recording is required. This is done by creating `device` objects along with their corresponding `electrodes`. Rather than repeating this information for each implant within the `<participant>.yaml` file, the `device` parameter in the `<participant>.yaml` file should be a name pointing to a device entry in a `devices.yaml`. A template for this file is included at `derivatives/exportNWB/templates/devices.yaml`. This `devices.yaml` should be structured as follows:

```
- name:           [name of device]
  electrode_qty:  [quantity of wired electrodes on the device]
  description:    [text description of the device]
  manufacturer:   [manufacturer of the device]

- name:           NeuroPort10x10
  electrode_qty:  96
  description:    10x10 96 channel NeuroPort array
  manufacturer    Blackrock Neurotech

- name:
  ...
```

The `<devices>.yaml` should exist in a `Data` directory one level above the execution path (assumed to be `realtime_rig_dev` at the moment). The `<participant>.yaml` should exist within the corresponding participant directory within this `Data` directory (e.g. `../Data/t0`). Templates for both files are located at `derivaties/exportNWB/templates` and can be copied to those respective folders and filled in as needed.

## File Storage

To stop a graph and save an NWB file, the `stopGraphAndSaveNWB` command must be sent to the `supervisor_ipstream` stream. Saved files are currently stored in a `../Data` folder one level above the execution path (assumed to be `realtime_rig_dev` at the moment). It will automatically create a new folder within `Session/Data` for the participant called `T<num>`, a new folder for the session within that `ses-<session_number>`, and a new folder within that called `NWB`. Within this folder, a file named `T<num>_ses-<session_number>.nwb` is saved. Future versions of the save functionality will use date and block information from the session metadata to create the directory structure and file name.
