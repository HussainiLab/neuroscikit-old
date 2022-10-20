import os, sys
import numpy as np

PROJECT_PATH = os.getcwd()
sys.path.append(PROJECT_PATH)

from library.study_space import Session, Study
# from x_io.rw.axona.batch_read import _read_cut
from _prototypes.unit_matcher.write_axona import get_current_cut_data, write_cut, format_new_cut_file_name, apply_remapping
from _prototypes.unit_matcher.read_axona import temp_read_cut
from _prototypes.unit_matcher.session import compare_sessions
from x_io.rw.axona.batch_read import make_study

"""

This module reads axona cut and tetrode files. DONE (batch_read in x_io or single pair read in read_axona)
It then extracts the spike waveforms from the cut file. DONE (batch_read or single pair read in read_axona)
It then matches the spike waveforms to the units in the tetrode file. DONE (part of core class loading)
It then produces a dictionary of the spike waveforms for each unit. DONE (No dictionary --> Core class with waveforms per Spike. Collection Spike = Cluster)
It then extracts features from the spike waveforms for each unit. 
It then matches the spike waveforms to the units in the tetrode file.
It then produces a remapping of the units in the tetrode file. 
It then applies the remapping to the cut file data. DONE (map dict changes cut data)
It then writes the remapped cut file data to a new cut file. DONE (new cut data writs to file)
Read, Retain, Map, Write
"""

def run_unit_matcher(paths=[], settings={}, study=None):
    if study is None:
        assert len(paths) > 0 and len(settings) > 0
        # make study --> will load + sort data: SpikeClusterBatch (many units) --> SpikeCluster (a unit) --> Spike (an event)
        study = make_study(paths, settings)
        # make animals
        study.make_animals()
    elif isinstance(study, Study):
        study.make_animals()

    print('Starting Unit Matching')

    for animal in study.animals:
        # SESSIONS INSIDE OF ANIMAL WILL BE SORTED SEQUENTIALLY AS PART OF ANIMAL(WORKSPACE) CLASS IN STUDY_SPACE.PY
        prev = None 
        curr = None 
        prev_map_dict = None
        isFirstSession = False
        
        session_mappings = {}
        comparison_count = 1
        for session in animal.sessions:
            curr = animal.sessions[session]

            # if first session of sequence there is no prev session
            if prev is not None:
                matches, match_distances, unmatched_2, unmatched_1 = compare_sessions(prev, curr)
                print('Comparison ' + str(comparison_count))
                print(matches, unmatched_1, unmatched_2)
                session_mappings[comparison_count] = {}
                session_mappings[comparison_count]['isFirstSession'] = isFirstSession
                session_mappings[comparison_count]['matches'] = matches
                session_mappings[comparison_count]['match_distances'] = match_distances
                session_mappings[comparison_count]['unmatched_2'] = unmatched_2
                session_mappings[comparison_count]['unmatched_1'] = unmatched_1
                session_mappings[comparison_count]['pair'] = (prev, curr)

                if isFirstSession:
                    isFirstSession = False

                comparison_count += 1

            else:
                isFirstSession = True

            prev = curr

        cross_session_matches, session_mappings = format_mapping_dicts(session_mappings)

        cross_session_matches = reorder_unmatched_cells(cross_session_matches)

        print(cross_session_matches)

        remapping_dicts = apply_cross_session_remapping(session_mappings, cross_session_matches)

        # for loop or iter thru output to write cut,
        # e.g.
        for map_dict in remapping_dicts:
            new_cut_file_path, new_cut_data, header_data = format_cut(map_dict['session'], map_dict['map_dict'])
            print('Writing mapping: ' + str(map_dict['map_dict']))
            write_cut(new_cut_file_path, new_cut_data, header_data)

    return study

def reorder_unmatched_cells(cross_session_matches):
    new_ordering = []

    for key in cross_session_matches:
        if len(cross_session_matches[key]['agg_matches']) > 0:
            new_ordering.append(cross_session_matches[key])

    for key in cross_session_matches:
        if len(cross_session_matches[key]['agg_matches']) == 0:
            new_ordering.append(cross_session_matches[key])

    new_cross_session_matches = {}
    c = 1
    for order in new_ordering:
        new_cross_session_matches[c] = order
        c += 1

    return new_cross_session_matches

def _agg_distances(cross_session_matches):
    cross_keys = list(cross_session_matches.keys())
    avg_JSD = {}
    cross_session_unmatched = []
    first_session_unmatched = []

    for cross_key in cross_keys:
        jsds = cross_session_matches[cross_key]['agg_distances']

        if len(jsds) > 0:
            avg_JSD[cross_key] = np.mean(jsds)
        else:
            avg_JSD[cross_key] = np.nan

            if 'unmatched_1' in cross_session_matches[cross_key]:
                first_session_unmatched.append(cross_key)
            if 'prev_unmatched' in cross_session_matches[cross_key]:
                cross_session_unmatched.append(cross_key)

    return avg_JSD, cross_session_unmatched, first_session_unmatched


def apply_cross_session_remapping(session_mappings, cross_session_matches):


    avg_JSD, cross_session_unmatched, first_session_unmatched = _agg_distances(cross_session_matches)

    print(cross_session_unmatched, first_session_unmatched)

    JSD_vals = np.array(list(avg_JSD.values()))
    JSD_keys = np.array(list(avg_JSD.keys()))

    JSD_keys = JSD_keys[JSD_vals == JSD_vals]
    JSD_vals = JSD_vals[JSD_vals == JSD_vals]

    if len(JSD_vals) > 0:
        sorted_JSD_vals_idx = np.argsort(JSD_vals)
        # sorted_JSD_vals = np.sort(JSD_vals)
        sorted_JSD_keys = JSD_keys[sorted_JSD_vals_idx]

        for i in range(len(sorted_JSD_keys)):
            key = sorted_JSD_keys[i]
            matches = np.array(cross_session_matches[key]['agg_matches']).reshape((-1,2))
            print('MATCHES')
            print(matches)
            comps = cross_session_matches[key]['comps']

            assert len(matches) == len(comps)

            prev_map_dict = None
            for j in range(len(comps)):
                pair = matches[j]


                # if first comparison for this match does not contain the first session, cell is unmatched in session2 when compares to session 1
                # E.g. session1- session2, cell 5 in ses2 not matched. But session2- session3, cell 5 in ses2 is matched
                # mapping dictionary from ses2 to ses1 needs to update to account for new match label in session2-session3 comparison
                if j == 0 and not session_mappings[comps[j]]['isFirstSession']:
                    print('SHOULD ONLY SEE THIS LINE ONCE')
                    map_to_update = session_mappings[comps[j]-1]['map_dict']
                    print(map_to_update)
                    map_to_update[pair[0]] = i + 1
                    print(map_to_update)

                    session_mappings[comps[j]-1]['map_dict'] = map_to_update

                    prev_map_dict = map_to_update
                    
                if session_mappings[comps[j]]['isFirstSession']:

                    first_ses_map_dict = session_mappings[comps[j]]['first_ses_map_dict']

                    print('step 1')
                    print(first_ses_map_dict)
                    first_ses_map_dict[pair[0]] = i + 1
                    print(first_ses_map_dict)

                    session_mappings[comps[j]]['first_ses_map_dict'] = first_ses_map_dict

                    prev_map_dict = first_ses_map_dict

                map_dict = session_mappings[comps[j]]['map_dict']

                if prev_map_dict is not None:
                    print('step 2')
                    print(map_dict)
                    map_dict[pair[1]] = prev_map_dict[pair[0]]
                    print(map_dict)
                else:
                    print('step 3')
                    print(map_dict)
                    map_dict[pair[1]] = i + 1
                    print(map_dict)

                session_mappings[comps[j]]['map_dict'] = map_dict

                prev_map_dict = map_dict


            # if last comparison for this match does not contain the last session, cell is unmatched in session 1 when compared to session2
            # E.g. session1- session2, cell 5 in ses2 is matched. But session2- session3, cell 5 in ses2 (ses1 in the comparison) is unmatched
            # mapping dictionary from ses2 to ses1 needs to update to account for new match label in session2-session3 comparison
            # if len(comps) < len(session_mappings):


        # add 1 for gap cell
        max_id = len(sorted_JSD_keys) + 1

        for i in range(len(cross_session_unmatched)):
            key = cross_session_unmatched[i]
            
            unmatched = cross_session_matches[key]['prev_unmatched']
            unmatched_comps = cross_session_matches[key]['unmatched_comps']

            for j in range(len(unmatched_comps)):
                map_dict = session_mappings[unmatched_comps[j]]['map_dict']
                
                max_id = max_id + i + 1
                map_dict[unmatched[j]] = max_id 

                session_mappings[unmatched_comps[j]]['map_dict'] = map_dict

        for i in range(len(first_session_unmatched)):
            key = first_session_unmatched[i]
            
            unmatched = cross_session_matches[key]['unmatched_1']
            unmatched_comps = cross_session_matches[key]['unmatched_1_comps']

            for j in range(len(unmatched_comps)):
                first_ses_map_dict = session_mappings[unmatched_comps[j]]['first_ses_map_dict']
                
                max_id = max_id + i + 1
                first_ses_map_dict[unmatched[j]] = max_id 

                session_mappings[unmatched_comps[j]]['first_ses_map_dict'] = first_ses_map_dict

    remapping_dicts = []
    for key in session_mappings:
        if session_mappings[key]['isFirstSession']:
            remapping_dicts.append({'map_dict': session_mappings[key]['first_ses_map_dict'], 'session': session_mappings[key]['pair'][0]})
        remapping_dicts.append({'map_dict': session_mappings[key]['map_dict'], 'session': session_mappings[key]['pair'][1]})
        

    return remapping_dicts

def format_mapping_dicts(session_mappings):
    cross_session_matches = {}
    prev_map_dict = None
    prev_matched_labels = None
    prev_unmatched = []
    
    for comparison in session_mappings:
        unmatched_2 = session_mappings[comparison]['unmatched_2']

        cross_session_matches, map_dict = make_mapping_dict(session_mappings, comparison, cross_session_matches)

        session_mappings[comparison]['map_dict'] = map_dict

        # if session_mappings[comparison]['isFirstSession']:
        #     prev_map_dict = session_mappings[comparison]['first_ses_map_dict']

        if prev_map_dict is not None:
            cross_session_matches, matched_labels, prev_matched_now_unmatched = match_cross_session_pairings(session_mappings, comparison, cross_session_matches, prev_map_dict, prev_matched_labels)
            cross_session_matches = check_prev_unmatched(session_mappings, comparison, cross_session_matches, prev_unmatched, matched_labels)

        else:
            matched_labels = None

            # if len(prev_unmatched) > 0:
            #     for i in range(len(prev_unmatched)):
            #         unmatched_id = prev_unmatched[i]
            #         cross_ses_key = max(list(cross_session_matches.keys())) + 1
            #         if unmatched_id in list(map_dict.values()):
            #             idx = np.where(unmatched_id in list(map_dict.values()))[0]
            #             cross_session_matches[cross_ses_key] = {}
            #             cross_session_matches[cross_ses_key]['agg_matches'] = []
            #             cross_session_matches[cross_ses_key]['agg_distances'] = []
            #             cross_session_matches[cross_ses_key]['comps'] = []
            #             cross_session_matches[cross_ses_key]['agg_matches'].append(matches[idx])
            #             cross_session_matches[cross_ses_key]['agg_distances'].append(match_distances[idx])
            #             cross_session_matches[cross_ses_key]['comps'].append(comparison)
            #             matched_labels[list(map_dict.keys())[idx]] = cross_ses_key
            #         else:
            #             cross_session_matches[cross_ses_key] = {}
            #             cross_session_matches[cross_ses_key]['agg_matches'] = []
            #             cross_session_matches[cross_ses_key]['agg_distances'] = []
            #             cross_session_matches[cross_ses_key]['comps'] = []
            #             cross_session_matches[cross_ses_key]['prev_unmatched'] = []
            #             cross_session_matches[cross_ses_key]['unmatched_comps'] = []
            #             cross_session_matches[cross_ses_key]['prev_unmatched'].append(unmatched_id)
            #             cross_session_matches[cross_ses_key]['unmatched_comps'].append(comparison)

        prev_map_dict = map_dict
        prev_matched_labels = matched_labels
        prev_unmatched = unmatched_2

    cross_session_matches = add_last_unmatched(comparison, cross_session_matches, prev_unmatched)
    
    return cross_session_matches, session_mappings


def make_mapping_dict(session_mappings, comparison, cross_session_matches):
    map_dict = {}
    match_distances = np.asarray(session_mappings[comparison]['match_distances'])
    matches = np.asarray(session_mappings[comparison]['matches'])
    unmatched_1 = session_mappings[comparison]['unmatched_1']

    if session_mappings[comparison]['isFirstSession']:
        first_ses_map_dict = {}
        for i in range(len(matches)):
            cross_session_matches[int(matches[i][1])] = {}
            cross_session_matches[int(matches[i][1])]['agg_matches'] = []
            cross_session_matches[int(matches[i][1])]['agg_distances'] = []
            cross_session_matches[int(matches[i][1])]['comps'] = []
            cross_session_matches[int(matches[i][1])]['agg_matches'].append(matches[i])
            cross_session_matches[int(matches[i][1])]['agg_distances'].append(match_distances[i])
            cross_session_matches[int(matches[i][1])]['comps'].append(comparison)

            # map_dict[int(matches[i][0])] = i + 1
            first_ses_map_dict[int(matches[i][0])] = int(matches[i][0])

        if len(unmatched_1) > 0:
            for i in range(len(unmatched_1)):
                cross_session_matches[int(unmatched_1[i])] = {}
                cross_session_matches[int(unmatched_1[i])]['agg_matches'] = []
                cross_session_matches[int(unmatched_1[i])]['agg_distances'] = []
                cross_session_matches[int(unmatched_1[i])]['comps'] = []
                cross_session_matches[int(unmatched_1[i])]['unmatched_1'] = []
                cross_session_matches[int(unmatched_1[i])]['unmatched_1_comps'] = []
                cross_session_matches[int(unmatched_1[i])]['unmatched_1'].append(int(unmatched_1[i]))
                cross_session_matches[int(unmatched_1[i])]['unmatched_1_comps'].append(comparison)

        session_mappings[comparison]['first_ses_map_dict'] = first_ses_map_dict

    for pair in matches:
        map_dict[int(pair[1])] = int(pair[0])

    session_mappings[comparison]['map_dict'] = map_dict

    return cross_session_matches, map_dict


def match_cross_session_pairings(session_mappings, comparison, cross_session_matches, prev_map_dict, prev_matched_labels):
    match_distances = np.asarray(session_mappings[comparison]['match_distances'])
    matches = np.asarray(session_mappings[comparison]['matches'])
    map_dict = session_mappings[comparison]['map_dict']

    prev_matched_now_unmatched = []

    matched_labels = {}
    for key in list(prev_map_dict.keys()):
        idx = np.where(np.array(list(map_dict.values())) == key)[0]
        if len(idx) > 0:
            idx = idx[0]

            if prev_matched_labels is None:
                cross_ses_key = key
            else:
                cross_ses_key = prev_matched_labels[key]

            cross_session_matches[cross_ses_key]['agg_matches'].append(matches[idx])
            cross_session_matches[cross_ses_key]['agg_distances'].append(match_distances[idx])
            cross_session_matches[cross_ses_key]['comps'].append(comparison)

            matched_labels[np.array(list(map_dict.keys()))[idx]] = cross_ses_key
        prev_matched_now_unmatched.append(key)

    return cross_session_matches, matched_labels, prev_matched_now_unmatched


def check_prev_unmatched(session_mappings, comparison, cross_session_matches, prev_unmatched, matched_labels):
    match_distances = np.asarray(session_mappings[comparison]['match_distances'])
    matches = np.asarray(session_mappings[comparison]['matches'])
    map_dict = session_mappings[comparison]['map_dict']

    if len(prev_unmatched) > 0:
        for i in range(len(prev_unmatched)):
            unmatched_id = prev_unmatched[i]
            cross_ses_key = max(list(cross_session_matches.keys())) + 1
            if unmatched_id in list(map_dict.values()):
                idx = np.where(np.array(list(map_dict.values())) == unmatched_id)[0][0]
                cross_session_matches[cross_ses_key] = {}
                cross_session_matches[cross_ses_key]['agg_matches'] = []
                cross_session_matches[cross_ses_key]['agg_distances'] = []
                cross_session_matches[cross_ses_key]['comps'] = []
                cross_session_matches[cross_ses_key]['agg_matches'].append(matches[idx])
                cross_session_matches[cross_ses_key]['agg_distances'].append(match_distances[idx])
                cross_session_matches[cross_ses_key]['comps'].append(comparison)
                matched_labels[list(map_dict.keys())[idx]] = cross_ses_key
                # nowMatched = True
            else:
                cross_session_matches[cross_ses_key] = {}
                cross_session_matches[cross_ses_key]['agg_matches'] = []
                cross_session_matches[cross_ses_key]['agg_distances'] = []
                cross_session_matches[cross_ses_key]['comps'] = []
                cross_session_matches[cross_ses_key]['prev_unmatched'] = []
                cross_session_matches[cross_ses_key]['unmatched_comps'] = []
                cross_session_matches[cross_ses_key]['prev_unmatched'].append(unmatched_id)
                cross_session_matches[cross_ses_key]['unmatched_comps'].append(comparison)
                # nowMatched = False

    return cross_session_matches

def add_last_unmatched(comparison, cross_session_matches, last_unmatched):
    if len(last_unmatched) > 0:
        for i in range(len(last_unmatched)):
            unmatched_id = last_unmatched[i]
            cross_ses_key = max(list(cross_session_matches.keys())) + 1
            cross_session_matches[cross_ses_key] = {}
            cross_session_matches[cross_ses_key]['agg_matches'] = []
            cross_session_matches[cross_ses_key]['agg_distances'] = []
            cross_session_matches[cross_ses_key]['comps'] = []
            cross_session_matches[cross_ses_key]['prev_unmatched'] = []
            cross_session_matches[cross_ses_key]['unmatched_comps'] = []
            cross_session_matches[cross_ses_key]['prev_unmatched'].append(unmatched_id)
            cross_session_matches[cross_ses_key]['unmatched_comps'].append(comparison)

    return cross_session_matches
 





# def run_unit_matcher(paths=[], settings={}, study=None):
#     if study is None:
#         assert len(paths) > 0 and len(settings) > 0
#         # make study --> will load + sort data: SpikeClusterBatch (many units) --> SpikeCluster (a unit) --> Spike (an event)
#         study = make_study(paths, settings)
#         # make animals
#         study.make_animals()
#     elif isinstance(study, Study):
#         study.make_animals()

#     print('Starting Unit Matching')

#     for animal in study.animals:
#         # SESSIONS INSIDE OF ANIMAL WILL BE SORTED SEQUENTIALLY AS PART OF ANIMAL(WORKSPACE) CLASS IN STUDY_SPACE.PY
#         prev = None 
#         curr = None 
#         prev_map_dict = None
#         isFirstSession = False
#         for session in animal.sessions:
#             curr = animal.sessions[session]

#             # print(prev, curr, isFirstSession)


#             # if first session of sequence there is no prev session
#             if prev is not None:
#                 matches, match_distances, unmatched_2, unmatched_1 = compare_sessions(prev, curr)

#                 if isFirstSession:
#                     map_dict_first = map_unit_matches_first_session(matches, match_distances, unmatched_1)
#                     first_ses_cut_file_path, new_cut_data, header_data = format_cut(prev, map_dict_first)
#                     # first_ses_cut_file_path = prev.session_metadata.file_paths['cut']
#                     # cut_data, header_data = get_current_cut_data(first_ses_cut_file_path)
#                     # new_cut_data = apply_remapping(cut_data, map_dict)
#                     # new_cut_file_path = format_new_cut_file_name(first_ses_cut_file_path)
#                     print('Writing mapping: ' + str(map_dict_first))
#                     write_cut(first_ses_cut_file_path, new_cut_data, header_data)
#                     isFirstSession = False
#                     # print('NEW')
#                     # print(map_dict_first.values())
#                     # print(map_dict_first.keys())
#                     prev_map_dict = map_dict_first

#                 # prev_cut_file_path = prev.session_metadata.file_paths['cut']
#                 # prev_matched_cut_file = format_new_cut_file_name(prev_cut_file_path)
#                 # updated_cut_data, _ = get_current_cut_data(prev_matched_cut_file)
#                 # updated_labels = np.unique(updated_cut_data)

#                 map_dict = map_unit_matches_sequential_session(matches, unmatched_2)

#                 # map dict is built on non matched cut labels, remap dict based on previous mapped dictionary
#                 values = list(map_dict.values())
#                 keys = list(map_dict.keys())
#                 for i in range(len(values)):
#                     if values[i] in prev_map_dict:
#                         map_dict[keys[i]] = prev_map_dict[values[i]]

#                 new_cut_file_path, new_cut_data, header_data = format_cut(curr, map_dict)
#                 print('Writing mapping: ' + str(map_dict))
#                 write_cut(new_cut_file_path, new_cut_data, header_data)
#                 prev_map_dict = map_dict
#                 # print('NEW')
#                 # print(map_dict.values())
#                 # print(map_dict.keys())
#             else:
#                 isFirstSession = True
#             # update refernece of first session in pair
#             # prev = curr
#             # curr = session

#             prev = curr

#     return study

def format_cut(session: Session, map_dict: dict):
    cut_file_path = session.session_metadata.file_paths['cut']
    cut_data, header_data = get_current_cut_data(cut_file_path)
    new_cut_data = apply_remapping(cut_data, map_dict)
    new_cut_file_path = format_new_cut_file_name(cut_file_path)
    return new_cut_file_path, new_cut_data, header_data


def map_unit_matches_sequential_session(matches, unmatched):
    map_dict = {}
    
    for pair in matches:
        map_dict[int(pair[1])] = int(pair[0])

    # highest_matched_id = max(map_dict, key=map_dict.get)
    highest_matched_id = max(map_dict.values())
    # unmatched = sorted(unmatched)
    empty_cell_id = highest_matched_id + 1
    unmatched_cell_start_id = empty_cell_id + 1
    for i in range(len(unmatched)):
        map_dict[unmatched[i]] = unmatched_cell_start_id + i
    # print('Mappings :' + str(map_dict))
    return map_dict

def map_unit_matches_first_session(matches, match_distances, unmatched):
    sort_ids = np.argsort(match_distances)
    matches = np.asarray(matches)[sort_ids]

    map_dict = {}

    for i in range(len(matches)):
        map_dict[int(matches[i][0])] = i + 1

    highest_matched_id = max(map_dict.values())
    # unmatched = sorted(unmatched)
    empty_cell_id = highest_matched_id + 1
    unmatched_cell_start_id = empty_cell_id + 1

    for i in range(len(unmatched)):
        map_dict[unmatched[i]] = unmatched_cell_start_id + i
    return map_dict

# def map_unit_matches(matches, match_distances, unmatched):
#     sort_ids = np.argsort(match_distances)
#     matches = np.asarray(matches)[sort_ids]

#     map_dict = {}
    
#     for pair in matches:
#         map_dict[int(pair[1])] = int(pair[0])

#     for i in range(len(matches))

#     highest_matched_id = max(map_dict, key=map_dict.get)
#     unmatched = sorted(unmatched)
#     empty_cell_id = highest_matched_id + 1
#     unmatched_cell_start_id = empty_cell_id + 1

#     for i in range(len(unmatched)):
#         map_dict[unmatched[i]] = unmatched_cell_start_id + i



#     return map_dict





"""

batch main fxn takes in study and does procedure across all pairs of sequenntial sessions

main fxn takes directory or session1 folder, session2 folder. 
    If directory assert only two sessions
    Figure out which session follows which
    Extract waveforms from cut
    Match waveforns to units from tetrode file (use sort by spike/cell fn)
    Return dictionary of spike waveforms for each unit (SpikeClusterBatch --> SpikeCluster --> Spike)

"""



# def match_session_units(session_1 : Session, session_2: Session):
#     """
#     Input is two sequential Session() instances from study workspace

#     session_2 follows session_1

#     Returns 
#     """

#     assert isinstance(session_1, Session), 'Make sure inputs are of Session() class type'
#     assert isinstance(session_2, Session), 'Make sure inputs are of Session() class type'

#     ### TO DO

#     # extracts features for every Spike in every SpikeCluster in SpikeClusterBatch (inputs are SpikeClusterBatch)
#     # unit_features = get_all_unit_features(SpikeCluster) --> Sorted colleciton of Spike() objects belonging to one unit

#     # match waveforms to units (inputs are SpikeCluster)
#     # matched_units = match_units(unit_featuress)

#     # best_matches = produce remapping (inputs are SpikeCluster)

#     # apply remapping(best_matches)

#     best_matches = {0:0, 1:2, 2:3, 3:4, 4:5, 5:6, 6:7, 7:0, 8:0, 9:0, 10:0, 11:0}

#     # print(np.unique(session_1.session_data.data['cell_ensemble'].get_label_ids()))
#     # print(np.unique(session_2.session_data.data['cell_ensemble'].get_label_ids()))

#     # print(np.unique(session_1.session_data.data['spike_cluster'].cluster_labels))
#     # print(np.unique(session_2.session_data.data['spike_cluster'].cluster_labels))

#     cut_file_path = session_2.session_metadata.file_paths['cut']

#     cut_data, header_data = get_current_cut_data(cut_file_path)

#     new_cut_data = apply_remapping(cut_data, best_matches)

#     new_cut_file_path = format_new_cut_file_name(cut_file_path)

#     return new_cut_file_path, new_cut_data, header_data

