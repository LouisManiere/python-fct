# coding: utf-8

"""
Extract Landover Raster within Valley Bottom

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
from multiprocessing import Pool
import click
import rasterio as rio
from ..config import DatasetParameter
from ..cli import starcall
from ..tileio import buildvrt

class Parameters:
    """
    Within valley-bottom lancover extraction parameters
    """

    tiles = DatasetParameter('domain tiles as CSV list', type='input')
    landcover = DatasetParameter('landcover raster map', type='input')
    mask = DatasetParameter('domain mask raster', type='input')
    output = DatasetParameter('valley bottom lancover', type='output')

    def __init__(self):
        """
        Default parameter values
        """

        self.tiles = 'shortest_tiles'
        self.landcover = 'landcover-bdt'
        self.mask = 'nearest_height'
        self.output = 'landcover_valley_bottom'

def ValleyBottomLandcoverTile(row, col, params):

    # tileset = config.tileset()

    mask_tile = params.mask.tilename(row=row, col=col)
    # tileset.tilename(
    #     # 'backup_valley_mask',
    #     'nearest_height',
    #     row=row,
    #     col=col
    # )

    raster_tile = params.landcover.tilename(row=row, col=col)
    # tileset.tilename(
    #     'landcover-bdt',
    #     row=row,
    #     col=col
    # )

    output = params.output.tilename(row=row, col=col)
    # tileset.tilename(
    #     'landcover_valley_bottom',
    #     row=row,
    #     col=col
    # )

    if not (os.path.exists(raster_tile) and os.path.exists(mask_tile)):
        return

    with rio.open(raster_tile) as ds:

        data = ds.read(1)
        nodata = ds.nodata
        profile = ds.profile.copy()

    with rio.open(mask_tile) as ds:

        mask = ds.read(1)
        data[mask == ds.nodata] = nodata

    with rio.open(output, 'w', **profile) as dst:
        dst.write(data, 1)

def ValleyBottomLandcover(params, processes=1, **kwargs):

    # tileset = config.tileset()
    tilefile = params.tiles.filename(**kwargs)
    # tileset.filename('shortest_tiles')

    def length():

        with open(tilefile) as fp:
            return sum(1 for line in fp)

    def arguments():

        with open(tilefile) as fp:
            for line in fp:

                row, col = tuple(int(x) for x in line.split(','))

                yield (
                    ValleyBottomLandcoverTile,
                    row,
                    col,
                    params,
                    {}
                )

    with Pool(processes=processes) as pool:

        pooled = pool.imap_unordered(starcall, arguments())

        with click.progressbar(pooled, length=length()) as iterator:
            for _ in iterator:
                pass

    buildvrt('default', params.output.name)
