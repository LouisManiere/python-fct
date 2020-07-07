# coding: utf-8

"""
Configuration Classes

***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

import click

from ..config import config
from .LandCover import MkLandCoverTiles
from .Population import DisaggregatePopulationData
from .SubGrid import (
    DefineSubGridMask,
    AggregatePopulation,
    AggregateLandCover,
    DominantLandCover
)

@click.group()
def cli():
    """
    DOCME
    """
    pass

@cli.command()
@click.option('--processes', '-j', default=1, help="Execute j parallel processes")
def landcover(processes=1):
    """
    Reclass landcover data and create landcover tiles
    """

    config.default()
    MkLandCoverTiles(processes)

@cli.command()
@click.option('--processes', '-j', default=1, help="Execute j parallel processes")
def population(processes=1):
    """
    Disaggregate population data to match the resolution of landcover data
    """

    config.default()
    DisaggregatePopulationData(processes)

@cli.group()
def subgrid():
    """
    SubGrid Aggregates
    """
    pass

@subgrid.command('mask')
def subgrid_mask():
    """
    Define SubGrid Mask
    """
    
    config.default()
    DefineSubGridMask()

@subgrid.command('population')
@click.option('--processes', '-j', default=1, help="Execute j parallel processes")
def subgrid_population(processes=1):
    """
    Aggregate population data
    """
    
    config.default()
    AggregatePopulation(processes)

@subgrid.command('landcover')
@click.option('--processes', '-j', default=1, help="Execute j parallel processes")
def subgrid_landcover(processes=1):
    """
    Aggregate landcover data
    """
    
    config.default()
    AggregateLandCover(processes)

@subgrid.command('dominant')
def subgrid_dominant_landcover():
    """
    Calculate dominant landcover at subgrid's resolution
    """
    
    config.default()
    DominantLandCover()
