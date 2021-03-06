"""Transformer for converting ply files to las
"""

import datetime
import os
import numpy as np
import laspy

from terrautils.spatial import scanalyzer_to_utm

from plyfile import PlyData

import configuration
import transformer_class

MM_PER_METER = 1000.0

def ply_to_array(input_paths: list, scan_distance: float, scan_direction: int, point_cloud_origin: dict, utm):
    """Read PLY files into a numpy matrix.

    :param input_paths: list of input PLY files or single file path
    :param scan_distance: from metadata
    :param scan_direction: from metadata
    :param point_cloud_origin: from metadata
    :param utm: True to return coordinates to UTM, False to return gantry fixed coordinates
    :return: tuple of (x_points, y_points, z_points, utm_bounds)
    """
    # pylint: disable=too-many-locals, too-many-statements
    # Create concatenated list of vertices to generate one merged LAS file
    first = True
    for plyf in input_paths:
        if plyf.find("west") > -1:
            curr_side = "west"
            cambox = [2.070, 2.726, 1.135]
        else:
            curr_side = "east"
            cambox = [2.070, 0.306, 1.135]

        plydata = PlyData.read(plyf)
        merged_x = plydata['vertex']['x']
        merged_y = plydata['vertex']['y']
        merged_z = plydata['vertex']['z']

        # Attempt fix using math from terrautils.spatial.calculate_gps_bounds
        fix_x = merged_x + cambox[0] + 0.082
        if scan_direction == 0:
            fix_y = merged_y + float(2.0*float(cambox[1])) - scan_distance/2.0 + (
                -0.354 if curr_side == 'east' else -4.363)
            utm_x, utm_y = scanalyzer_to_utm(
                (fix_x * 0.001) + point_cloud_origin['x'],
                (fix_y * 0.001) + point_cloud_origin['y']/2.0 - 0.1
            )
        else:
            fix_y = merged_y + float(2.0*float(cambox[1])) - scan_distance/2.0 + (
                4.2 if curr_side == 'east' else -3.43)
            utm_x, utm_y = scanalyzer_to_utm(
                (fix_x * 0.001) + point_cloud_origin['x'],
                (fix_y * 0.001) + point_cloud_origin['y']/2.0 + 0.4
            )
        fix_z = merged_z + cambox[2]
        utm_z = (fix_z * 0.001) + point_cloud_origin['z']

        # Create matrix of fixed gantry coords for TIF, but min/max of UTM coords for georeferencing
        if first:
            if utm:
                x_pts = utm_x
                y_pts = utm_y
            else:
                x_pts = fix_x
                y_pts = fix_y
            z_pts = utm_z

            min_x_utm = np.min(utm_x)
            min_y_utm = np.min(utm_y)
            max_x_utm = np.max(utm_x)
            max_y_utm = np.max(utm_y)

            first = False
        else:
            if utm:
                x_pts = np.concatenate([x_pts, utm_x])
                y_pts = np.concatenate([y_pts, utm_y])
            else:
                x_pts = np.concatenate([x_pts, fix_x])
                y_pts = np.concatenate([y_pts, fix_y])
            z_pts = np.concatenate([z_pts, utm_z])

            min_x_utm2 = np.min(utm_x)
            min_y_utm2 = np.min(utm_y)
            max_x_utm2 = np.max(utm_x)
            max_y_utm2 = np.max(utm_y)

            min_x_utm = min_x_utm if min_x_utm < min_x_utm2 else min_x_utm2
            min_y_utm = min_y_utm if min_y_utm < min_y_utm2 else min_y_utm2
            max_x_utm = max_x_utm if max_x_utm > max_x_utm2 else max_x_utm2
            max_y_utm = max_y_utm if max_y_utm > max_y_utm2 else max_y_utm2

    bounds = (min_y_utm, max_y_utm, min_x_utm, max_x_utm)

    return (x_pts, y_pts, z_pts, bounds)


def generate_las_from_ply(input_paths: list, output_path: str, scan_distance: float, scan_direction: int,
                          point_cloud_origin: dict, utm: bool):
    """Read PLY file to array and write that array to an LAS file.

    :param input_paths: list of input PLY files or single file path
    :param output_path: output LAS file
    :param scan_distance: from metadata
    :param scan_direction: from metadata
    :param point_cloud_origin: from metadata
    :param utm: True to return coordinates to UTM, False to return gantry fixed coordinates
    """
    (x_pts, y_pts, z_pts, bounds) = ply_to_array(input_paths, scan_distance, scan_direction, point_cloud_origin, utm)

    # Create header and populate with scale and offset
    las_info = laspy.base.Writer(output_path, 'w', laspy.header.Header())
    las_info.header.offset = [np.floor(np.min(y_pts)),
                              np.floor(np.min(x_pts)),
                              np.floor(np.min(z_pts))]
    if utm:
        las_info.header.scale = [.000001, .000001, .000001]
    else:
        las_info.header.scale = [1, 1, .000001]

    las_info.set_x(y_pts, True)
    las_info.set_y(x_pts, True)
    las_info.set_z(z_pts, True)
    las_info.set_header_property("x_max", np.max(y_pts))
    las_info.set_header_property("x_min", np.min(y_pts))
    las_info.set_header_property("y_max", np.max(x_pts))
    las_info.set_header_property("y_min", np.min(x_pts))
    las_info.set_header_property("z_max", np.max(z_pts))
    las_info.set_header_property("z_min", np.min(z_pts))
    las_info.close()

    return bounds


def perform_process(transformer: transformer_class.Transformer, check_md: dict, transformer_md: dict, full_md: list) -> dict:
    """Performs the processing of the data
    Arguments:
        transformer: instance of transformer class
    Return:
        Returns a dictionary with the results of processing
    """
    # pylint: disable=unused-argument
    result = {}
    file_md = []

    file_list = check_md['list_files']()

    # Extract necessary parameters from metadata
    for one_metadata in full_md:
        if 'sensor_variable_metadata' in one_metadata:
            scan_distance = float(one_metadata['sensor_variable_metadata']['scan_distance_mm'])/MM_PER_METER
            scan_direction = int(one_metadata['sensor_variable_metadata']['scan_direction'])
            point_cloud_origin = one_metadata['sensor_variable_metadata']['point_cloud_origin_m']['east']
            break

    try:
        ply_files = []
        transformer_info = transformer.generate_transformer_md()
        for one_file in file_list:
            if one_file.endswith(".ply"):
                ply_files.append(os.path.join(check_md['working_folder'], one_file))
        if ply_files:
            out_file = ply_files[0].replace(".ply", ".las")
            generate_las_from_ply(ply_files, out_file, scan_distance, scan_direction, point_cloud_origin, True)

            file_md.append({
                'path': out_file,
                'key': configuration.TRANSFORMER_SENSOR,
                'metadata': {
                    'data': {
                        'name': transformer_info['name'],
                        'version': transformer_info['version'],
                        'source': ','.join(file_list),
                        'utc_timestamp': datetime.datetime.now().isoformat()
                    }
                }
            })
        result['code'] = 0
        result['file'] = file_md
        result[configuration.TRANSFORMER_NAME] = {
            **transformer_info,
            'utc_timestamp': datetime.datetime.now().isoformat()
        }

    except Exception as ex:
        result['code'] = -1
        result['error'] = "Exception caught converting PLY files: %s" % str(ex)

    return result
