# coding: utf-8

"""
Longitudinal swath generation :
discretize space along reference axis

***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 3 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

import os
import math
from operator import itemgetter
from collections import namedtuple
from multiprocessing import Pool

import numpy as np
from scipy.spatial import cKDTree

import click
import xarray as xr

import rasterio as rio
from rasterio import features
import fiona
import fiona.crs
from shapely.geometry import asShape, Polygon

from ..config import (
    config,
    LiteralParameter,
    DatasetParameter
)
# from ..tileio import ReadRasterTile
from ..tileio import as_window
from ..rasterize import rasterize_linestring, rasterize_linestringz
from .. import transform as fct
from .. import speedup
from .. import terrain_analysis as ta
from ..cli import starcall
from ..metadata import set_metadata

def nearest_value_and_distance(refpixels, domain, nodata):
    """
    Returns distance in pixels !
    """

    height, width = domain.shape
    midpoints = 0.5*(refpixels + np.roll(refpixels, 1, axis=0))
    midpoints_valid = (refpixels[:-1, 3] == refpixels[1:, 3])
    # midpoints = midpoints[1:, :2][midpoints_valid]
    midpoints = midpoints[1:, :2]
    midpoints[~midpoints_valid, 0] = -999999.0
    midpoints[~midpoints_valid, 1] = -999999.0

    midpoints_index = cKDTree(midpoints, balanced_tree=True)
    distance = np.zeros_like(domain)
    values = np.copy(distance)
    nearest_axes = np.zeros_like(domain, dtype='uint32')

    # semi-vectorized code, easier to understand

    # for i in range(height):

    #     js = np.arange(width)
    #     row = np.column_stack([np.full_like(js, i), js])
    #     valid = domain[row[:, 0], row[:, 1]] != nodata
    #     query_pixels = row[valid]
    #     nearest_dist, nearest_idx = midpoints_index.query(query_pixels, k=1, jobs=4)
    #     nearest_a = np.take(refpixels, nearest_idx, axis=0, mode='wrap')
    #     nearest_b = np.take(refpixels, nearest_idx+1, axis=0, mode='wrap')
    #     nearest_m = np.take(midpoints[:, 2], nearest_idx+1, axis=0, mode='wrap')
    #     # same as
    #     # nearest_value = 0.5*(nearest_a[:, 2] + nearest_b[:, 2])
    #     dist, signed_dist, pos = ta.signed_distance(
    #         np.float32(nearest_a),
    #         np.float32(nearest_b),
    #         np.float32(query_pixels))

    # faster fully-vectorized code

    pixi, pixj = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
    valid = domain != nodata
    query_pixels = np.column_stack([pixi[valid], pixj[valid]])

    del pixi
    del pixj
    del valid

    _, nearest_idx = midpoints_index.query(query_pixels, k=1)

    # nearest_a = np.take(refpixels, nearest_idx, axis=0, mode='wrap')
    # nearest_b = np.take(refpixels, nearest_idx+1, axis=0, mode='wrap')

    nearest_p = np.take(refpixels, np.column_stack([nearest_idx, nearest_idx+1]), axis=0, mode='wrap')
    nearest_a = nearest_p[:, 0, :]
    nearest_b = nearest_p[:, 1, :]

    dist, signed_dist, pos = ta.signed_distance(
        np.float32(nearest_a),
        np.float32(nearest_b),
        np.float32(query_pixels))

    # interpolate between points A and B
    nearest_value = nearest_a[:, 2] + pos*(nearest_b[:, 2] - nearest_a[:, 2])

    nearest_axis = np.copy(nearest_a[:, 3])
    nearest_axis[nearest_axis != nearest_b[:, 3]] = 0

    # almost same as
    # nearest_m = 0.5*(nearest_a[:, 2] + nearest_b[:, 2])
    # same as
    # nearest_m = np.take(midpoints[:, 2], nearest_idx+1, axis=0, mode='wrap')

    distance[query_pixels[:, 0], query_pixels[:, 1]] = dist * np.sign(signed_dist)
    values[query_pixels[:, 0], query_pixels[:, 1]] = nearest_value
    nearest_axes[query_pixels[:, 0], query_pixels[:, 1]] = nearest_axis

    return nearest_axes, values, distance

# SwathMeasurementParams = namedtuple('SwathMeasurementParams', [
#     'ax_mask',
#     'ax_reference',
#     'ax_talweg_distance',
#     'output_distance',
#     'output_measure',
#     'output_nearest',
#     'output_swaths_raster',
#     'output_swaths_shapefile',
#     'output_swaths_bounds',
#     'mdelta'
# ])

# def DefaultParameters():
#     """
#     Default parameters (valley swath units)
#     """

#     return dict(
#         ax_mask='ax_nearest_height',
#         ax_reference='ax_refaxis',
#         output_distance='ax_axis_distance',
#         output_measure='ax_axis_measure',
#         output_swaths_raster='ax_dgo',
#         output_swaths_shapefile='ax_dgo_parts',
#         output_swaths_bounds='ax_dgo_defs',
#         mdelta=200.0
#     )

# def ValleyBottomParameters():
#     """
#     Create swaths units using talweg reference axis
#     and first-iteration valley bottom mask
#     """

#     return dict(
#         # ax_mask='ax_valley_mask',
#         ax_mask='nearest_height',
#         ax_reference='refaxis',
#         ax_talweg_distance='nearest_distance',
#         output_distance='axis_distance',
#         output_measure='axis_measure',
#         output_nearest='axis_nearest',
#         output_swaths_raster='swaths_refaxis',
#         output_swaths_shapefile='swaths_refaxis_polygons',
#         output_swaths_bounds='swaths_refaxis_bounds',
#         mdelta=200.0
#     )

class Parameters:
    """
    Swath measurement parameters
    """

    tiles = DatasetParameter('')
    mask = DatasetParameter('')
    reference = DatasetParameter('')
    talweg_distance = DatasetParameter('')
    output_distance = DatasetParameter('')
    output_measure = DatasetParameter('')
    output_nearest = DatasetParameter('')
    output_swaths_raster = DatasetParameter('')
    output_swaths_shapefile = DatasetParameter('')
    output_swaths_bounds = DatasetParameter('')
    mdelta = LiteralParameter('')

    def __init__(self):
        """
        Default parameter values
        """

        self.tiles = 'shortest_tiles'
        self.mask = 'nearest_height'
        self.reference = 'refaxis'
        self.talweg_distance = 'nearest_distance'
        self.output_distance = 'axis_distance'
        self.output_measure = 'axis_measure'
        self.output_nearest = 'axis_nearest'
        self.output_swaths_raster = 'swaths_refaxis'
        self.output_swaths_shapefile = 'swaths_refaxis_polygons'
        self.output_swaths_bounds = 'swaths_refaxis_bounds'
        self.mdelta = 200.0


def DisaggregateTileIntoSwaths(row, col, params, **kwargs):
    """
    see CarveLongitudinalSwaths
    """

    # tileset = config.tileset()
    # # height_raster = tileset.tilename('ax_flow_height', axis=axis, row=row, col=col)

    # def _tilename(dataset):
    #     return tileset.tilename(
    #         dataset,
    #         row=row,
    #         col=col)

    refaxis_shapefile = params.reference.filename(tileset=None)
    # config.filename(params.ax_reference)
    mask_raster = params.mask.tilename(row=row, col=col)
    # _tilename(params.ax_mask)

    output_distance = params.output_distance.tilename(row=row, col=col)
    # _tilename(params.output_distance)
    output_measure = params.output_measure.tilename(row=row, col=col)
    # _tilename(params.output_measure)
    output_nearest = params.output_nearest.tilename(row=row, col=col)
    # _tilename(params.output_nearest)
    output_swaths_raster = params.output_swaths_raster.tilename(row=row, col=col)
    # _tilename(params.output_swaths_raster)

    mdelta = params.mdelta

    if not os.path.exists(mask_raster):
        return {}

    with rio.open(mask_raster) as ds:

        # click.echo('Read Valley Bottom')

        # valley_bottom = speedup.raster_buffer(ds.read(1), ds.nodata, 6.0)
        mask = ds.read(1)
        height, width = mask.shape

        # distance = np.full_like(valley_bottom, ds.nodata)
        # measure = np.copy(distance)
        refaxis_pixels = list()

        # click.echo('Map Stream Network')

        def accept(i, j):
            return all([i >= -height, i < 2*height, j >= -width, j < 2*width])

        coord = itemgetter(0, 1)

        mmin = float('inf')
        mmax = float('-inf')

        with fiona.open(refaxis_shapefile) as fs:
            for feature in fs:

                axis = feature['properties']['AXIS']
                m0 = feature['properties'].get('M0', 0.0)
                length = asShape(feature['geometry']).length

                if m0 < mmin:
                    mmin = m0

                if m0 + length > mmax:
                    mmax = m0 + length

                coordinates = np.array([
                    coord(p) + (m0,) for p in reversed(feature['geometry']['coordinates'])
                ], dtype='float32')

                coordinates[1:, 2] = m0 + np.cumsum(np.linalg.norm(
                    coordinates[1:, :2] - coordinates[:-1, :2],
                    axis=1))

                coordinates[:, :2] = ta.worldtopixel(coordinates[:, :2], ds.transform, gdal=False)

                for a, b in zip(coordinates[:-1], coordinates[1:]):
                    for i, j, m in rasterize_linestringz(a, b):
                        if accept(i, j):
                            # distance[i, j] = 0
                            # measure[i, j] = m
                            refaxis_pixels.append((i, j, m, axis))

        # ta.shortest_distance(axr, ds.nodata, startval=1, distance=distance, feedback=ta.ConsoleFeedback())
        # ta.shortest_ref(axr, ds.nodata, startval=1, fillval=0, out=measure, feedback=ta.ConsoleFeedback())

        if not refaxis_pixels:
            return []

        mmin = math.floor(mmin / mdelta) * mdelta
        mmax = math.ceil(mmax / mdelta) * mdelta
        breaks = np.arange(mmin, mmax + mdelta, mdelta)

        # click.echo('Calculate Measure & Distance Raster')

        # Option 1, shortest distance

        # speedup.shortest_value(valley_bottom, measure, ds.nodata, distance, 1000.0)
        # distance = 5.0 * distance
        # distance[valley_bottom == ds.nodata] = ds.nodata
        # measure[valley_bottom == ds.nodata] = ds.nodata
        # Add 5.0 m x 10 pixels = 50.0 m buffer
        # distance2 = np.zeros_like(valley_bottom)
        # speedup.shortest_value(domain, measure, ds.nodata, distance2, 10.0)

        # Option 2, nearest using KD Tree

        nearest, measure, distance = nearest_value_and_distance(
            np.flip(np.array(refaxis_pixels), axis=0),
            np.float32(mask),
            ds.nodata)

        nodata = -99999.0
        distance = 5.0 * distance
        distance[mask == ds.nodata] = nodata
        measure[mask == ds.nodata] = nodata

        # click.echo('Write output')

        profile = ds.profile.copy()
        profile.update(compress='deflate', dtype='float32', nodata=nodata)

        with rio.open(output_distance, 'w', **profile) as dst:
            dst.write(distance, 1)

        with rio.open(output_measure, 'w', **profile) as dst:
            dst.write(measure, 1)

        profile.update(dtype='uint32', nodata=0)

        with rio.open(output_nearest, 'w', **profile) as dst:
            dst.write(nearest, 1)

        # click.echo('Create DGOs')

        dgo = np.zeros_like(measure, dtype='uint32')
        attrs = dict()

        for axis in np.unique(nearest):

            if axis == 0:
                continue

            ax_mask = (nearest == axis)
            ax_measure = measure[ax_mask]
            
            # mmin = math.floor(np.min(ax_measure) / mdelta) * mdelta
            # mmax = math.ceil(np.max(ax_measure) / mdelta) * mdelta
            # breaks = np.arange(mmin, mmax + mdelta, mdelta)

            dgo[ax_mask] = np.uint32(np.digitize(ax_measure, breaks))

            def calculate_attrs():

                measures = np.round(0.5 * (breaks + np.roll(breaks, 1)), 1)
                ax_dgo = np.zeros_like(dgo)
                ax_dgo[ax_mask] = dgo[ax_mask]
                boxes = speedup.flat_boxes(ax_dgo)

                if not boxes:
                    return dict()

                maximinj = itemgetter(2, 1)
                minimaxj = itemgetter(0, 3)

                lowerleft = fct.pixeltoworld(np.array([
                    maximinj(box) for box in boxes.values()
                ], dtype='int32'), ds.transform)

                upperright = fct.pixeltoworld(np.array([
                    minimaxj(box) for box in boxes.values()
                ], dtype='int32'), ds.transform)

                bounds = np.column_stack([lowerleft, upperright])

                return {
                    (axis, swath): (measures[swath], bounds[k])
                    for k, swath in enumerate(boxes)
                    if swath > 0
                }

            attrs.update(calculate_attrs())

        profile.update(nodata=0, dtype='uint32')

        with rio.open(output_swaths_raster, 'w', **profile) as dst:
            dst.write(dgo, 1)

        return attrs

def DisaggregateIntoSwaths(params, processes=1, **kwargs):
    """
    Calculate measurement support rasters and
    create discrete longitudinal swath units along the reference axis

    @api    fct-swath:discretize

    @input  reference_axis: ax_refaxis
    @input  mask: ax_valley_mask
    @input  tiles: ax_shortest_tiles
    @param  mdelta: 200.0

    @output measure: ax_axis_measure
    @output distance: ax_axis_distance
    @output swath_raster: ax_valley_swaths
    @output swath_polygons: ax_valley_swaths_polygons
    @output swath_bounds: ax_valley_swaths_bounds
    """

    # parameters = ValleyBottomParameters()
    # parameters.update({key: kwargs[key] for key in kwargs.keys() & parameters.keys()})
    # kwargs = {key: kwargs[key] for key in kwargs.keys() - parameters.keys()}
    # params = SwathMeasurementParams(**parameters)

    tilefile = params.tiles.filename() # config.tileset().filename(ax_tiles)

    def length():

        with open(tilefile) as fp:
            return sum(1 for line in fp)

    def arguments():

        with open(tilefile) as fp:
            tiles = [tuple(int(x) for x in line.split(',')) for line in fp]

        for row, col in tiles:
            yield (
                DisaggregateTileIntoSwaths,
                row,
                col,
                params,
                kwargs
            )

    g_attrs = dict()

    def merge_bounds(bounds1, bounds2):

        return (
            min(bounds1[0], bounds2[0]),
            min(bounds1[1], bounds2[1]),
            max(bounds1[2], bounds2[2]),
            max(bounds1[3], bounds2[3]),
        )

    def merge(attrs):

        if not attrs:
            # multiprocessing unpickles empty dict as list
            return

        g_attrs.update({
            key: (
                g_attrs[key][0],
                merge_bounds(g_attrs[key][1], attrs[key][1])
            )
            for key in attrs.keys() & g_attrs.keys()
        })

        g_attrs.update({
            key: (attrs[key][0], tuple(attrs[key][1]))
            for key in attrs.keys() - g_attrs.keys()
        })

    with Pool(processes=processes) as pool:

        pooled = pool.imap_unordered(starcall, arguments())

        with click.progressbar(pooled, length=length()) as iterator:
            for attrs in iterator:
                merge(attrs)

    return g_attrs

def WriteSwathsBounds(params, attrs, **kwargs):
    """
    Write swath coordinates (id, location on ref axis)
    and bounds (minx, miny, maxx, maxy)
    to netcdf file
    """

    # parameters = ValleyBottomParameters()
    # parameters.update({key: kwargs[key] for key in kwargs.keys() & parameters.keys()})
    # kwargs = {key: kwargs[key] for key in kwargs.keys() - parameters.keys()}
    # params = SwathMeasurementParams(**parameters)

    axes_swaths = np.array(list(attrs.keys()), dtype='uint32')
    measures = np.array([value[0] for value in attrs.values()], dtype='float32')
    bounds = np.array([value[1] for value in attrs.values()], dtype='float32')

    dataset = xr.Dataset(
        {
            'axis': (('unit',), axes_swaths[:, 0]),
            'swath': (('unit',), axes_swaths[:, 1]),
            'measure': (('unit',), measures),
            'bounds': (('unit', 'coord'), bounds),
            'delta_measure': params.mdelta
        },
        coords={
            'coord': ['minx', 'miny', 'maxx', 'maxy']
        })

    set_metadata(dataset, 'swath_bounds')

    dataset.attrs['geographic_object'] = params.ax_mask
    dataset.attrs['reference_axis'] = params.ax_reference

    output = params.output_swaths_bounds.filename(tileset=None) # config.filename(params.output_swaths_bounds)

    dataset.to_netcdf(
        output, 'w',
        encoding={
            'measure': dict(zlib=True, complevel=9, least_significant_digit=0),
            'bounds': dict(zlib=True, complevel=9, least_significant_digit=2),
            'swath': dict(zlib=True, complevel=9)
        })

    return dataset

def ReadSwathsBounds(params):

    filename = params.output_swaths_bounds.filename(tileset=None) # config.filename(params.output_swaths_bounds)
    dataset = xr.open_dataset(filename)
    dataset.load()

    dataset = dataset.sortby(['axis', 'measure'])

    return {
        (dataset['axis'].values[k], dataset['swath'].values[k]): (
            dataset['measure'].values[k],
            tuple(dataset['bounds'].values[k, :]))
        for k in range(dataset['measure'].shape[0])
    }

def VectorizeOneSwathPolygon(axis, gid, measure, bounds, params, **kwargs):
    """
    Vectorize swath polygon connected to talweg
    """

    # tileset = config.tileset()

    nearest_axes_raster = params.output_nearest.filename() # tileset.filename(params.output_nearest)
    swath_raster = params.output_swaths_raster.filename() # tileset.filename(params.output_swaths_raster)
    # mask_raster = tileset.filename(params.ax_mask, axis=axis)
    # distance_raster = tileset.filename(params.output_distance, axis=axis)
    distance_raster = params.talweg_distance.filename() # tileset.filename(params.ax_talweg_distance)

    with rio.open(nearest_axes_raster) as ds:

        window = as_window(bounds, ds.transform)
        nearest_axes = ds.read(1, window=window, boundless=True, fill_value=ds.nodata)

    with rio.open(swath_raster) as ds:

        window = as_window(bounds, ds.transform)
        swath = ds.read(1, window=window, boundless=True, fill_value=ds.nodata)

    with rio.open(distance_raster) as ds:

        window = as_window(bounds, ds.transform)
        distance = ds.read(1, window=window, boundless=True, fill_value=ds.nodata)

        state = np.full_like(swath, 255, dtype='uint8')
        state[(nearest_axes == axis) & (swath == gid)] = 0
        state[(state == 0) & (distance == 0)] = 1

        height, width = state.shape

        if height == 0 or width == 0:
            click.secho('Invalid swath %d with height = %d and width = %d' % (gid, height, width), fg='red')
            return gid, measure, list()

        # out = np.full_like(state, 255, dtype='uint32')
        distance = np.zeros_like(state, dtype='float32')

        speedup.continuity_mask(
            state,
            # out,
            distance,
            jitter=0.4)

        # vectorize state => 0: outer space, 2: inner unit

        transform = ds.transform * ds.transform.translation(
            window.col_off,
            window.row_off)

        polygons = features.shapes(
            state,
            state != 255,
            connectivity=8,
            transform=transform)

        return axis, gid, measure, list(polygons)

def VectorizeSwathPolygons(params, processes=1, **kwargs):
    """
    Vectorize spatial units' polygons
    """

    # parameters = ValleyBottomParameters()
    # parameters.update({key: kwargs[key] for key in kwargs.keys() & parameters.keys()})
    # kwargs = {key: kwargs[key] for key in kwargs.keys() - parameters.keys()}
    # params = SwathMeasurementParams(**parameters)

    defs = ReadSwathsBounds(params)

    def arguments():

        for (axis, gid), (measure, bounds) in defs.items():
            yield (
                VectorizeOneSwathPolygon,
                axis,
                gid,
                measure,
                bounds,
                params,
                kwargs
            )

    output = params.output_swaths_shapefile.filename(tileset=None)
    # config.filename(params.output_swaths_shapefile, mod=False)

    schema = {
        'geometry': 'Polygon',
        'properties': [
            ('GID', 'int'),
            ('AXIS', 'int:4'),
            ('VALUE', 'int:4'),
            # ('ROW', 'int:3'),
            # ('COL', 'int:3'),
            ('M', 'float:10.2')
        ]
    }
    crs = fiona.crs.from_epsg(config.srid)
    options = dict(driver='ESRI Shapefile', crs=crs, schema=schema)

    with fiona.open(output, 'w', **options) as dst:

        with Pool(processes=processes) as pool:

            pooled = pool.imap_unordered(starcall, arguments())

            with click.progressbar(pooled, length=len(defs)) as iterator:
                for axis, gid, measure, polygons in iterator:
                    for (polygon, value) in polygons:

                        geom = asShape(polygon)
                        exterior = Polygon(geom.exterior).buffer(0)

                        feature = {
                            'geometry': exterior.__geo_interface__,
                            'properties': {
                                'GID': int(gid),
                                'AXIS': int(axis),
                                'VALUE': int(value),
                                # 'ROW': row,
                                # 'COL': col,
                                'M': float(measure)
                            }
                        }

                        dst.write(feature)

                        for ring in geom.interiors:

                            if not exterior.contains(ring):

                                feature = {
                                    'geometry': Polygon(ring).buffer(0).__geo_interface__,
                                    'properties': {
                                        'GID': int(gid),
                                        'AXIS': int(axis),
                                        'VALUE': int(value),
                                        # 'ROW': row,
                                        # 'COL': col,
                                        'M': float(measure)
                                    }
                                }

                                dst.write(feature)

def UpdateSwathTile(axis, tile, params):

    # tileset = config.tileset()

    # def _tilename(name):
    #     return tileset.tilename(name, axis=axis, row=tile.row, col=tile.col)

    swath_shapefile = params.output_swaths_shapefile.filename(tileset=None, axis=axis)
    # config.filename(params.output_swaths_shapefile, axis=axis)
    swath_raster = params.output_swaths_raster.tilename(axis=axis, row=tile.row, col=tile.col)
    # _tilename(params.output_swaths_raster)

    if not os.path.exists(swath_raster):
        return

    with rio.open(swath_raster) as ds:

        swaths = ds.read(1)
        shape = ds.shape
        nodata = ds.nodata
        transform = ds.transform
        profile = ds.profile.copy()
        profile.update(compress='deflate', dtype='uint32')

    with fiona.open(swath_shapefile) as fs:

        def accept(feature):
            return all([
                feature['properties']['AXIS'] == axis,
                feature['properties']['VALUE'] != 2
            ])

        geometries = [
            (f['geometry'], 1) for f in fs.filter(bbox=tile.bounds)
            if accept(f)
        ]

        if geometries:

            mask_invalid = features.rasterize(
                geometries,
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype='int32')

            mask_invalid = features.sieve(mask_invalid, 40) # TODO externalize parameter
            swaths[mask_invalid == 1] = nodata

    with rio.open(swath_raster, 'w', **profile) as dst:
        dst.write(swaths, 1)

def UpdateSwathRaster(axis, params, processes=1, **kwargs):
    """
    Commit manual swath edits to swaths raster

    @api    fct-swath:update

    @input  tiles: ax_shortest_tiles
    @input  swath_raster: ax_valley_swaths

    @param  sieve_threshold: 40

    @output swath_raster: ax_valley_swaths
    """

    # parameters = ValleyBottomParameters()
    # parameters.update({key: kwargs[key] for key in kwargs.keys() & parameters.keys()})
    # kwargs = {key: kwargs[key] for key in kwargs.keys() - parameters.keys()}
    # params = SwathMeasurementParams(**parameters)

    tileset = config.tileset()

    def arguments():

        for tile in tileset.tiles():
            yield (
                UpdateSwathTile,
                axis,
                tile,
                params,
                kwargs
            )

    with Pool(processes=processes) as pool:

        pooled = pool.imap_unordered(starcall, arguments())
        with click.progressbar(pooled, length=len(tileset)) as iterator:
            for _ in iterator:
                pass
