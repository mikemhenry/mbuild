from __future__ import division

from collections import OrderedDict
from copy import deepcopy
from math import floor, radians, sqrt
import re
import json
from itertools import combinations_with_replacement

import numpy as np
import operator
from oset import oset as OrderedSet

from mbuild import Box
from mbuild.utils.io import import_
from mbuild.utils.sorting import natural_sort
from mbuild.utils.geometry import coord_shift
from mbuild.utils.conversion import RB_to_OPLS

__all__ = ['write_gsd']


def write_gsd(structure, filename, ref_distance=1.0, ref_mass=1.0,
              ref_energy=1.0, rigid_bodies=None, shift_coords=True,
              write_special_pairs=True, auto_scale=False):
    """Output a GSD file (HOOMD v2 default data format).

    Parameters
    ----------
    structure : parmed.Structure
        ParmEd Structure object
    filename : str
        Path of the output file.
    ref_distance : float, optional, default=1.0
        Reference distance for conversion to reduced units
    ref_mass : float, optional, default=1.0
        Reference mass for conversion to reduced units
    ref_energy : float, optional, default=1.0
        Reference energy for conversion to reduced units
    rigid_bodies : list of int, optional, default=None
        List of rigid body information. An integer value is required for
        each atom corresponding to the index of the rigid body the particle
        is to be associated with. A value of None indicates the atom is not
        part of a rigid body.
    shift_coords : bool, optional, default=True
        Shift coordinates from (0, L) to (-L/2, L/2) if necessary.
    write_special_pairs : bool, optional, default=True
        Writes out special pair information necessary to correctly use the OPLS fudged 1,4 interactions
        in HOOMD.
    auto_scale : bool, optional, default=False
        Automatically use largest sigma value as ref_distance, largest mass value
        as ref_mass and largest epsilon value as ref_energy.

    Notes
    -----
    Force field parameters are not written to the GSD file and must be included
    manually into a HOOMD input script. Work on a HOOMD plugin is underway to
    read force field parameters from a Foyer XML file.

    """

    import_('gsd')
    import gsd.hoomd

    xyz = np.array([[atom.xx, atom.xy, atom.xz] for atom in structure.atoms])
    if shift_coords:
        xyz = coord_shift(xyz, structure.box[:3])

    gsd_file = gsd.hoomd.Snapshot()

    gsd_file.configuration.step = 0
    gsd_file.configuration.dimensions = 3

    # Write box information
    if np.allclose(structure.box[3:6], np.array([90, 90, 90])):
        gsd_file.configuration.box = np.hstack((structure.box[:3] / ref_distance,
                                                np.zeros(3)))
    else:
        a, b, c = structure.box[0:3] / ref_distance
        alpha, beta, gamma = np.radians(structure.box[3:6])

        lx = a
        xy = b * np.cos(gamma)
        xz = c * np.cos(beta)
        ly = np.sqrt(b**2 - xy**2)
        yz = (b*c*np.cos(alpha) - xy*xz) / ly
        lz = np.sqrt(c**2 - xz**2 - yz**2)

        gsd_file.configuration.box = np.array([lx, ly, lz, xy, xz, yz])

    forcefield = True
    # create ff dict
    ff_params = {}
    if structure[0].type == '':
        forcefield = False
    if auto_scale and forcefield:
        ref_mass = max([atom.mass for atom in structure.atoms])
        pair_coeffs = list(set((atom.type,
                                atom.epsilon,
                                atom.sigma) for atom in structure.atoms))
        ref_energy = max(pair_coeffs, key=operator.itemgetter(1))[1]
        ref_distance = max(pair_coeffs, key=operator.itemgetter(2))[2]
        ff_params["ref_units"] = {"ref_mass": ref_mass, "ref_energy": ref_energy, "ref_distance": ref_distance}



    _write_particle_information(gsd_file, structure, xyz, ref_distance,
            ref_mass, ref_energy, rigid_bodies, ff_params, forcefield)
    if write_special_pairs:
        _write_pair_information(gsd_file, structure, ff_params, forcefield)
    if structure.bonds:
        _write_bond_information(gsd_file, structure, ff_params, forcefield, ref_distance, ref_energy)
    if structure.angles:
        _write_angle_information(gsd_file, structure, ff_params, forcefield, ref_energy)
    if structure.rb_torsions:
        _write_dihedral_information(gsd_file, structure, ff_params, forcefield, ref_energy)


    gsd.hoomd.create(filename, gsd_file)
    # write ff dict
    if ff_params:
        with open('ff_params.json', 'w') as outfile:
            json.dump(ff_params, outfile, indent=2)

def _write_particle_information(gsd_file, structure, xyz, ref_distance,
        ref_mass, ref_energy, rigid_bodies, ff_params, forcefield):
    """Write out the particle information.

    """

    gsd_file.particles.N = len(structure.atoms)
    gsd_file.particles.position = xyz / ref_distance

    types = [atom.name if atom.type == '' else atom.type
             for atom in structure.atoms]

    unique_types = list(set(types))
    unique_types.sort(key=natural_sort)
    gsd_file.particles.types = unique_types

    typeids = np.array([unique_types.index(t) for t in types])
    gsd_file.particles.typeid = typeids

    masses = np.array([atom.mass for atom in structure.atoms])
    masses[masses==0] = 1.0
    gsd_file.particles.mass = masses / ref_mass

    charges = np.array([atom.charge for atom in structure.atoms])
    e0 = 2.39725e-4
    '''
    Permittivity of free space = 2.39725e-4 e^2/((kcal/mol)(angstrom)),
    where e is the elementary charge
    '''
    charge_factor = (4.0*np.pi*e0*ref_distance*ref_energy)**0.5
    gsd_file.particles.charge = charges / charge_factor

    if rigid_bodies:
        rigid_bodies = [-1 if body is None else body for body in rigid_bodies]
    gsd_file.particles.body = rigid_bodies

    if forcefield:
        pair_coeffs = list(set((atom.type,
                                atom.epsilon,
                                atom.sigma) for atom in structure.atoms))
        pair_coeffs.sort(key=lambda pair_type: pair_type[0])
        ff_params["pair_coeffs"] = {}
        for param_set in pair_coeffs:
            ff_params["pair_coeffs"][param_set[0]] = { "alpha": 1.0, "epsilon": param_set[1]/ref_energy, "r_cut": 2.5,
                                                       "r_on": 2.5, "sigma": param_set[2]/ref_distance}
        ff_params["pair_coeffs_parameters"] = {}
        for A, B in combinations_with_replacement(pair_coeffs, 2):
            ff_params["pair_coeffs_parameters"]["{}-{}".format(A[0], B[0])] = { "alpha": 1.0, "epsilon":
                                                                    sqrt(A[1]/ref_energy * B[1]/ref_energy), "r_cut": 2.5,
                                                       "r_on": 2.5, "sigma": (A[2]/ref_distance + B[2]/ref_distance)/2}


def _write_pair_information(gsd_file, structure, ff_params, forcefield):
    """Write the special pairs in the system.

        Parameters
    ----------
    gsd_file :
        The file object of the GSD file being written
    structure : parmed.Structure
        Parmed structure object holding system information
    """
    pair_types = []
    pair_typeid = []
    pairs = []
    for ai in structure.atoms:
        for aj in ai.dihedral_partners:
            #make sure we don't double add
            if ai.idx > aj.idx:
                ps = '-'.join(sorted([ai.type, aj.type], key=natural_sort))
                if ps not in pair_types:
                    pair_types.append(ps)
                pair_typeid.append(pair_types.index(ps))
                pairs.append((ai.idx, aj.idx))
    gsd_file.pairs.types = pair_types
    gsd_file.pairs.typeid = pair_typeid
    gsd_file.pairs.group = pairs
    gsd_file.pairs.N = len(pairs)

def _write_bond_information(gsd_file, structure, ff_params, forcefield, ref_distance, ref_energy):
    """Write the bonds in the system.

    Parameters
    ----------
    gsd_file :
        The file object of the GSD file being written
    structure : parmed.Structure
        Parmed structure object holding system information

    """

    gsd_file.bonds.N = len(structure.bonds)

    unique_bond_types = set()
    _unique_bond_types = set()
    for bond in structure.bonds:
        t1, t2 = bond.atom1.type, bond.atom2.type
        if t1 == '' or t2 == '':
            t1, t2 = bond.atom1.name, bond.atom2.name
        t1, t2 = sorted([t1, t2], key=natural_sort)
        try:
            _bond_type = ('-'.join((t1, t2)), bond.type.k, bond.type.req)
            bond_type = ('-'.join((t1, t2)))
            _unique_bond_types.add(_bond_type)
        except AttributeError: # no forcefield applied, bond.type is None
            bond_type = ('-'.join((t1, t2)))
        unique_bond_types.add(bond_type)
    unique_bond_types = sorted(list(unique_bond_types), key=natural_sort)
    gsd_file.bonds.types = unique_bond_types

    bond_typeids = []
    bond_groups = []
    for bond in structure.bonds:
        t1, t2 = bond.atom1.type, bond.atom2.type
        if t1 == '' or t2 == '':
            t1, t2 = bond.atom1.name, bond.atom2.name
        t1, t2 = sorted([t1, t2], key=natural_sort)
        try:
            bond_type = ('-'.join((t1, t2)))
        except AttributeError: # no forcefield applied, bond.type is None
            bond_type = ('-'.join((t1, t2)), 0.0, 0.0)
        bond_typeids.append(unique_bond_types.index(bond_type))
        bond_groups.append((bond.atom1.idx, bond.atom2.idx))

    gsd_file.bonds.typeid = bond_typeids
    gsd_file.bonds.group = bond_groups
    ff_params["bond_coeffs"] = {}
    for bond_type, k, req in _unique_bond_types:
        ff_params["bond_coeffs"][bond_type] = {"k": k * 2.0 / ref_energy * ref_distance**2.0, "r0": req/ref_distance}


def _write_angle_information(gsd_file, structure, ff_params, forcefield, ref_energy):
    """Write the angles in the system.

    Parameters
    ----------
    gsd_file :
        The file object of the GSD file being written
    structure : parmed.Structure
        Parmed structure object holding system information

    """

    gsd_file.angles.N = len(structure.angles)

    unique_angle_types = set()
    _unique_angle_types = set()
    for angle in structure.angles:
        t1, t2, t3 = angle.atom1.type, angle.atom2.type, angle.atom3.type
        t1, t3 = sorted([t1, t3], key=natural_sort)
        angle_type = ('-'.join((t1, t2, t3)))
        unique_angle_types.add(angle_type)
    unique_angle_types = sorted(list(unique_angle_types), key=natural_sort)
    gsd_file.angles.types = unique_angle_types

    angle_typeids = []
    angle_groups = []
    for angle in structure.angles:
        t1, t2, t3 = angle.atom1.type, angle.atom2.type, angle.atom3.type
        t1, t3 = sorted([t1, t3], key=natural_sort)
        angle_type = ('-'.join((t1, t2, t3)))
        _angle_type = ('-'.join((t1, t2, t3)), angle.type.k, angle.type.theteq)
        _unique_angle_types.add(_angle_type)
        angle_typeids.append(unique_angle_types.index(angle_type))
        angle_groups.append((angle.atom1.idx, angle.atom2.idx,
                             angle.atom3.idx))

    gsd_file.angles.typeid = angle_typeids
    gsd_file.angles.group = angle_groups

    ff_params["angle_coeffs"] = {}
    for angle_type, k, teq in _unique_angle_types:
        ff_params["angle_coeffs"][angle_type] = {"k": k * 2.0 / ref_energy, "t0": radians(teq)}


def _write_dihedral_information(gsd_file, structure, ff_params, forcefield, ref_energy):
    """Write the dihedrals in the system.

    Parameters
    ----------
    gsd_file :
        The file object of the GSD file being written
    structure : parmed.Structure
        Parmed structure object holding system information

    """

    gsd_file.dihedrals.N = len(structure.rb_torsions)

    unique_dihedral_types = set()
    _unique_dihedral_types = set()
    for dihedral in structure.rb_torsions:
        t1, t2 = dihedral.atom1.type, dihedral.atom2.type
        t3, t4 = dihedral.atom3.type, dihedral.atom4.type
        if [t2, t3] == sorted([t2, t3], key=natural_sort):
            dihedral_type = ('-'.join((t1, t2, t3, t4)))
        else:
            dihedral_type = ('-'.join((t4, t3, t2, t1)))
        _dihedral_type = (dihedral_type, dihedral.type.c0,
        dihedral.type.c1, dihedral.type.c2, dihedral.type.c3, dihedral.type.c4,
        dihedral.type.c5, dihedral.type.scee, dihedral.type.scnb)
        _unique_dihedral_types.add(_dihedral_type)
        unique_dihedral_types.add(dihedral_type)
    unique_dihedral_types = sorted(list(unique_dihedral_types), key=natural_sort)
    gsd_file.dihedrals.types = unique_dihedral_types

    dihedral_typeids = []
    dihedral_groups = []
    for dihedral in structure.rb_torsions:
        t1, t2 = dihedral.atom1.type, dihedral.atom2.type
        t3, t4 = dihedral.atom3.type, dihedral.atom4.type
        if [t2, t3] == sorted([t2, t3], key=natural_sort):
            dihedral_type = ('-'.join((t1, t2, t3, t4)))
        else:
            dihedral_type = ('-'.join((t4, t3, t2, t1)))
        dihedral_typeids.append(unique_dihedral_types.index(dihedral_type))
        dihedral_groups.append((dihedral.atom1.idx, dihedral.atom2.idx,
                                dihedral.atom3.idx, dihedral.atom4.idx))

    gsd_file.dihedrals.typeid = dihedral_typeids
    gsd_file.dihedrals.group = dihedral_groups

    ff_params["dihedral_coeffs"] = {}
    for dihedral_type, c0, c1, c2, c3, c4, c5, scee, scnb in _unique_dihedral_types:
        opls_coeffs = RB_to_OPLS(c0, c1, c2, c3, c4, c5)
        opls_coeffs /= ref_energy
        k1, k2, k3, k4 = opls_coeffs
        ff_params["dihedral_coeffs"][dihedral_type] = {"k1": k1, "k2": k2, "k3": k3, "k4": k4}
