#!/usr/bin/env python
# Copyright 2004 Kristian Rother.
# Revisions copyright 2004 Thomas Hamelryck.
#
# This file is part of the Biopython distribution and governed by your
# choice of the "Biopython License Agreement" or the "BSD 3-Clause License".
# Please see the LICENSE file that should have been included as part of this
# package.

"""Parse header of PDB files into a python dictionary.

Emerged from the Columba database project www.columba-db.de, original author
Kristian Rother.
"""


import re

from Bio import File


def _get_journal(inl):
    # JRNL        AUTH   L.CHEN,M.DOI,F.S.MATHEWS,A.Y.CHISTOSERDOV,           2BBK   7
    journal = ""
    for l in inl:
        if re.search(r"\AJRNL", l):
            journal += l[19:72].lower()
    journal = re.sub(r"\s\s+", " ", journal)
    return journal


def _get_references(inl):
    # REMARK   1 REFERENCE 1                                                  1CSE  11
    # REMARK   1  AUTH   W.BODE,E.PAPAMOKOS,D.MUSIL                           1CSE  12
    references = []
    actref = ""
    for l in inl:
        if re.search(r"\AREMARK   1", l):
            if re.search(r"\AREMARK   1 REFERENCE", l):
                if actref != "":
                    actref = re.sub(r"\s\s+", " ", actref)
                    if actref != " ":
                        references.append(actref)
                    actref = ""
            else:
                actref += l[19:72].lower()

    if actref != "":
        actref = re.sub(r"\s\s+", " ", actref)
        if actref != " ":
            references.append(actref)
    return references


# bring dates to format: 1909-01-08
def _format_date(pdb_date):
    """Convert dates from DD-Mon-YY to YYYY-MM-DD format (PRIVATE)."""
    date = ""
    year = int(pdb_date[7:])
    if year < 50:
        century = 2000
    else:
        century = 1900
    date = str(century + year) + "-"
    all_months = [
        "xxx",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    month = str(all_months.index(pdb_date[3:6]))
    if len(month) == 1:
        month = "0" + month
    date = date + month + "-" + pdb_date[:2]
    return date


def _chop_end_codes(line):
    """Chops lines ending with  '     1CSA  14' and the like (PRIVATE)."""
    return re.sub(r"\s\s\s\s+[\w]{4}.\s+\d*\Z", "", line)


def _chop_end_misc(line):
    """Chops lines ending with  '     14-JUL-97  1CSA' and the like (PRIVATE)."""
    return re.sub(r"\s+\d\d-\w\w\w-\d\d\s+[1-9][0-9A-Z]{3}\s*\Z", "", line)


def _nice_case(line):
    """Make A Lowercase String With Capitals (PRIVATE)."""
    line_lower = line.lower()
    s = ""
    i = 0
    nextCap = 1
    while i < len(line_lower):
        c = line_lower[i]
        if c >= "a" and c <= "z" and nextCap:
            c = c.upper()
            nextCap = 0
        elif c in " .,;:\t-_":
            nextCap = 1
        s += c
        i += 1
    return s


def parse_pdb_header(infile):
    """Return the header lines of a pdb file as a dictionary.

    Dictionary keys are: head, deposition_date, release_date, structure_method,
    resolution, structure_reference, journal_reference, author and
    compound.
    """
    header = []
    with File.as_handle(infile) as f:
        for l in f:
            record_type = l[0:6]
            if record_type in ("ATOM  ", "HETATM", "MODEL "):
                break
            else:
                header.append(l)
    return _parse_pdb_header_list(header)


def _parse_remark_465(line):
    """Parse missing residue remarks.

    Returns a dictionary describing the missing residue.
    The specification for REMARK 465 at
    http://www.wwpdb.org/documentation/file-format-content/format33/remarks2.html#REMARK%20465
    only gives templates, but does not say they have to be followed.
    So we assume that not all pdb-files with a REMARK 465 can be understood.

    Returns a dictionary with the following keys:
    "model", "res_name", "chain", "ssseq", "insertion"
    """
    if line:
        # Note that line has been stripped.
        assert line[0] != " " and line[-1] not in "\n ", "line has to be stripped"
    pattern = re.compile(
        r"""
        (\d+\s[\sA-Z][\sA-Z][A-Z] |   # Either model number + residue name
            [A-Z]{1,3})               # Or only residue name with 1 (RNA) to 3 letters
        \s ([A-Za-z0-9])              # A single character chain
        \s+(-?\d+[A-Za-z]?)$          # Residue number: A digit followed by an optional
                                      # insertion code (Hetero-flags make no sense in
                                      # context with missing res)
        """,
        re.VERBOSE,
    )
    match = pattern.match(line)
    if match is None:
        return None
    residue = {}
    if " " in match.group(1):
        model, residue["res_name"] = match.group(1).split()
        residue["model"] = int(model)
    else:
        residue["model"] = None
        residue["res_name"] = match.group(1)
    residue["chain"] = match.group(2)
    try:
        residue["ssseq"] = int(match.group(3))
    except ValueError:
        residue["insertion"] = match.group(3)[-1]
        residue["ssseq"] = int(match.group(3)[:-1])
    else:
        residue["insertion"] = None
    return residue


def _parse_pdb_header_list(header):
    # database fields
    pdbh_dict = {
        "name": "",
        "head": "",
        "idcode": "",
        "deposition_date": "1909-01-08",
        "release_date": "1909-01-08",
        "structure_method": "unknown",
        "resolution": None,
        "structure_reference": "unknown",
        "journal_reference": "unknown",
        "author": "",
        "compound": {"1": {"misc": ""}},
        "source": {"1": {"misc": ""}},
        "has_missing_residues": False,
        "missing_residues": [],
        "helices": [],
        "sheets": [],
        "ss_bonds": [],
        "links": [],
        "cis_peptides": [],
        "sites": [],
    }

    def __get_helix_type(i):
        if   i ==  1:
            return "Right-handed alpha"
        elif i ==  2:
            return "Right-handed omega"
        elif i ==  3:
            return "Right-handed pi"
        elif i ==  4:
            return "Right-handed gamma"
        elif i ==  5:
            return "Right-handed 310"
        elif i ==  6:
            return "Left-handed alpha"
        elif i ==  7:
            return "Left-handed omega"
        elif i ==  8:
            return "Left-handed gamma"
        elif i ==  9:
            return "27 ribbon/helix"
        elif i == 10:
            return "Polyproline"
        else:
            return None

    pdbh_dict["structure_reference"] = _get_references(header)
    pdbh_dict["journal_reference"] = _get_journal(header)
    comp_molid = "1"
    last_comp_key = "misc"
    last_src_key = "misc"
    sheets = []
    n_res_site = 0

    for hh in header:
        h = re.sub(r"[\s\n\r]*\Z", "", hh)  # chop linebreaks off
        # key=re.sub("\s.+\s*","",h)
        key = h[:6].strip()
        # tail=re.sub("\A\w+\s+\d*\s*","",h)
        tail = h[10:].strip()
        # print("%s:%s" % (key, tail)

        # From here, all the keys from the header are being parsed
        if key == "TITLE":
            name = _chop_end_codes(tail).lower()
            pdbh_dict["name"] = " ".join([pdbh_dict["name"], name]).strip()
        elif key == "HEADER":
            rr = re.search(r"\d\d-\w\w\w-\d\d", tail)
            if rr is not None:
                pdbh_dict["deposition_date"] = _format_date(_nice_case(rr.group()))
            rr = re.search(r"\s+([1-9][0-9A-Z]{3})\s*\Z", tail)
            if rr is not None:
                pdbh_dict["idcode"] = rr.group(1)
            head = _chop_end_misc(tail).lower()
            pdbh_dict["head"] = head
        elif key == "COMPND":
            tt = re.sub(r"\;\s*\Z", "", _chop_end_codes(tail)).lower()
            # look for E.C. numbers in COMPND lines
            rec = re.search(r"\d+\.\d+\.\d+\.\d+", tt)
            if rec:
                pdbh_dict["compound"][comp_molid]["ec_number"] = rec.group()
                tt = re.sub(r"\((e\.c\.)*\d+\.\d+\.\d+\.\d+\)", "", tt)
            tok = tt.split(":")
            if len(tok) >= 2:
                ckey = tok[0]
                cval = re.sub(r"\A\s*", "", tok[1])
                if ckey == "mol_id":
                    pdbh_dict["compound"][cval] = {"misc": ""}
                    comp_molid = cval
                    last_comp_key = "misc"
                else:
                    pdbh_dict["compound"][comp_molid][ckey] = cval
                    last_comp_key = ckey
            else:
                pdbh_dict["compound"][comp_molid][last_comp_key] += tok[0] + " "
        elif key == "SOURCE":
            tt = re.sub(r"\;\s*\Z", "", _chop_end_codes(tail)).lower()
            tok = tt.split(":")
            # print(tok)
            if len(tok) >= 2:
                ckey = tok[0]
                cval = re.sub(r"\A\s*", "", tok[1])
                if ckey == "mol_id":
                    pdbh_dict["source"][cval] = {"misc": ""}
                    comp_molid = cval
                    last_src_key = "misc"
                else:
                    pdbh_dict["source"][comp_molid][ckey] = cval
                    last_src_key = ckey
            else:
                pdbh_dict["source"][comp_molid][last_src_key] += tok[0] + " "
        elif key == "KEYWDS":
            kwd = _chop_end_codes(tail).lower()
            if "keywords" in pdbh_dict:
                pdbh_dict["keywords"] += " " + kwd
            else:
                pdbh_dict["keywords"] = kwd
        elif key == "EXPDTA":
            expd = _chop_end_codes(tail)
            # chop junk at end of lines for some structures
            expd = re.sub(r"\s\s\s\s\s\s\s.*\Z", "", expd)
            # if re.search('\Anmr',expd,re.IGNORECASE): expd='nmr'
            # if re.search('x-ray diffraction',expd,re.IGNORECASE): expd='x-ray diffraction'
            pdbh_dict["structure_method"] = expd.lower()
        elif key == "CAVEAT":
            # make Annotation entries out of these!!!
            pass
        elif key == "REVDAT":
            rr = re.search(r"\d\d-\w\w\w-\d\d", tail)
            if rr is not None:
                pdbh_dict["release_date"] = _format_date(_nice_case(rr.group()))
        elif key == "JRNL":
            # print("%s:%s" % (key, tail))
            if "journal" in pdbh_dict:
                pdbh_dict["journal"] += tail
            else:
                pdbh_dict["journal"] = tail
        elif key == "AUTHOR":
            auth = _nice_case(_chop_end_codes(tail))
            if "author" in pdbh_dict:
                pdbh_dict["author"] += auth
            else:
                pdbh_dict["author"] = auth
        elif key == "REMARK":
            if re.search("REMARK   2 RESOLUTION.", hh):
                r = _chop_end_codes(re.sub("REMARK   2 RESOLUTION.", "", hh))
                r = re.sub(r"\s+ANGSTROM.*", "", r)
                try:
                    pdbh_dict["resolution"] = float(r)
                except ValueError:
                    # print('nonstandard resolution %r' % r)
                    pdbh_dict["resolution"] = None
            elif hh.startswith("REMARK 465"):
                if tail:
                    pdbh_dict["has_missing_residues"] = True
                    missing_res_info = _parse_remark_465(tail)
                    if missing_res_info:
                        pdbh_dict["missing_residues"].append(missing_res_info)
            elif hh.startswith("REMARK  99 ASTRAL"):
                if tail:
                    remark_99_keyval = tail.replace("ASTRAL ", "").split(": ")
                    if type(remark_99_keyval) == list and len(remark_99_keyval) == 2:
                        if "astral" not in pdbh_dict:
                            pdbh_dict["astral"] = {
                                remark_99_keyval[0]: remark_99_keyval[1]
                            }
                        else:
                            pdbh_dict["astral"][remark_99_keyval[0]] = remark_99_keyval[1]
        elif key == "HELIX":
            pdbh_dict["helices"].append({"serial_number":               int(hh[ 7:10]),
                                         "helix_id":                        hh[11:14],
                                         "initial_residue_name":            hh[15:18],
                                         "chain_id":                        hh[19],
                                         "initial_sequence_number":     int(hh[21:25]),
                                         "initial_insertation_code":        hh[25],
                                         "terminal_residue_name":           hh[27:30].strip(),
                                         "terminal_sequence_number":    int(hh[33:37]),
                                         "terminal_insertation_code":       hh[37],
                                         "class_number":                int(hh[38:40]),
                                         "helix_type": __get_helix_type(int(hh[38:40])),
                                         "comment":                         hh[40:70].strip(),
                                         "length":                      int(hh[71:76])})
        elif key == "SHEET":
            strand = {"strand":                   int(hh[ 7:10]),
                      "sheet_id":                     hh[11:14],
                      "number_of_strands":        int(hh[14:16]),
                      "initial_residue_name":         hh[17:20].strip(),
                      "initial_chain_id":             hh[21],
                      "initial_sequence_number":  int(hh[22:26]),
                      "initial_insertation_code":     hh[26],
                      "terminal_residue_name":        hh[28:31].strip(),
                      "terminal_chain_id":            hh[32],
                      "terminal_sequence_number": int(hh[33:37]),
                      "terminal_insertation_code":    hh[37],
                      "sense":                    int(hh[38:40]),
                      "current_atom_name":            None,
                      "current_residue_name":         None,
                      "current_chain_id":             None,
                      "current_sequence_number":      None,
                      "current_insertation_code":     None,
                      "previous_atom_name":           None,
                      "previous_residue_name":        None,
                      "previous_chain_id":            None,
                      "previous_sequence_number":     None,
                      "previous_insertation_code":    None}
            try:
                strand[10:20] = {"current_atom_name":            hh[41:45],
                                 "current_residue_name":         hh[45:48].strip(),
                                 "current_chain_id":             hh[49],
                                 "current_sequence_number":  int(hh[50:54]),
                                 "current_insertation_code":     hh[54],
                                 "previous_atom_name":           hh[56:60],
                                 "previous_residue_name":        hh[60:63].strip(),
                                 "previous_chain_id":            hh[64],
                                 "previous_sequence_number": int(hh[65:69]),
                                 "previous_insertation_code":    hh[69]}
            except Exception:
                pass
            if strand["sheet_id"] in sheets:
                pdbh_dict["sheets"][-1].append(strand)
            else:
                pdbh_dict["sheets"].append([strand])
                sheets.append(strand["sheet_id"])
        elif key == "SSBOND":
            pdbh_dict["ss_bonds"].append({"serial_number":       int(hh[7:10]),
                                          "chain_id_1":              hh[15],
                                          "sequence_number_1":   int(hh[17:21]),
                                          "insertaion_code_1":       hh[21],
                                          "chain_id_2":              hh[29],
                                          "sequence_number_2":   int(hh[31:35]),
                                          "insertation_code_2":      hh[35],
                                          "symmetry_operator_1": int(hh[59:65]),
                                          "symmetry_operator_2": int(hh[66:72]),
                                          "bond_distance":     float(hh[73:78])})
        elif key == "LINK":
            pdbh_dict["links"].append({"atom_name_1":                   hh[12:16],
                                       "alt_loc_1":                     hh[17],
                                       "residue_name_1":                hh[17:20].strip(),
                                       "chain_id_1":                    hh[22],
                                       "residue_sequence_number_1": int(hh[22:26]),
                                       "insertaion_code_1":             hh[26],
                                       "atom_name_2":                   hh[42:46],
                                       "alt_loc_2":                     hh[46],
                                       "residue_name_2":                hh[47:50].strip(),
                                       "chain_id_2":                    hh[51],
                                       "residue_sequence_number_2": int(hh[52:56]),
                                       "insertaion_code_2":             hh[56],
                                       "symmetry_operator_1":       int(hh[59:65]),
                                       "symmetry_operator_2":       int(hh[66:72]),
                                       "link_distance":           float(hh[73:78])})
        elif key == "CISPEP":
            pdbh_dict["cis_peptides"].append({"serial_number":                 hh[ 7:10],
                                              "residue_name_1":                hh[11:14].strip(),
                                              "chain_id_1":                    hh[15],
                                              "residue_sequence_number_1": int(hh[17:21]),
                                              "insertaion_code_1":             hh[21],
                                              "residue_name_2":                hh[25:28].strip(),
                                              "chain_id_2":                    hh[29],
                                              "residue_sequence_number_2": int(hh[31:35]),
                                              "insertaion_code_2":             hh[35],
                                              "model_number":              int(hh[43:46]),
                                              "angle":                   float(hh[53:59])})
        elif key == "SITE":
            if not int(hh[7:10]) - 1:
                n_res_site = int(hh[15:17])
                pdbh_dict["sites"].append({"site_id": hh[11:14],
                                           "residues": []})
            if n_res_site < 4:
                n_res_mod = n_res_site % 4
            else:
                n_res_mod = 4
                n_res_site -= 4
            site = [{"residue_name":                hh[i:i+3].strip(),
                     "chain_id":                    hh[i+4],
                     "residue_sequence_number": int(hh[i+5:i+9]),
                     "insertation_code":            hh[i+10]}
                    for i in range(18, 1 + n_res_mod * 11, 11)]
            pdbh_dict["sites"][-1]["residues"] += site
        else:
            # print(key)
            pass
    if pdbh_dict["structure_method"] == "unknown":
        res = pdbh_dict["resolution"]
        if res is not None and res > 0.0:
            pdbh_dict["structure_method"] = "x-ray diffraction"
    return pdbh_dict
