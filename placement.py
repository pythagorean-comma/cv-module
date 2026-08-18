"""Where every part sits on the board, in millimetres.

Separate from gen_pcb.py for the reason the mixer separates them: this file is
plain arithmetic and imports nothing from KiCad, so it can be read, diffed and
checked by anything -- while gen_pcb.py can only run under KiCad's own
interpreter. A placement that lives inside the thing that needs `pcbnew` is a
placement nobody can look at without KiCad.

**It is the floorplan made into coordinates, and that is the whole design of
it.** floorplan.py has been a placement *contract* for three passes -- zones,
their adjacency, and the argument for each -- with nothing to hold it to.
Every band below names the zone it implements, and check_zones() asserts that
the parts in a band are the parts floorplan.py puts in that zone. The two
cannot drift apart without one of them failing.

Two properties are checked rather than eyeballed, because they are the two that
a drawing cannot show:

  * **every part has a position**, and an unmatched reference is an error and
    not a default. The same argument floorplan.check_domains() makes about
    ground: a default answers the question silently;
  * **no two courtyards overlap**, against the estimates in SIZE. DRC on the
    real board is the authority and this is the fast version of it: the first
    placement drew 262 violations, of which 25 were courtyards and the rest
    were what a collision does to silk and mask, and finding those through
    KiCad is a minute a time where finding them here is a second.

The grid: twelve rows on a 7.62 mm pitch, two per channel. The odd row carries
that channel's audio path west to east, the even row carries its CV filter and
its envelope detector. Quad packages serve four channels each, so they sit in
their own columns spanning the rows they feed -- which is why the columns are
declared as x positions and the packages as (x, y) pairs.
"""

import math
import re

import design
import floorplan

# The grid. 7.62 mm is three times the 2.54 the connectors use and twice the
# 3.81 an 0805 needs with clearance -- and it is the pitch at which a SOIC-14
# body (8.7 mm long, 3.9 wide) fits between two rows without its courtyard
# reaching either.
ROW_PITCH = 7.62
AUDIO_ROW_0 = 12.0
CV_ROW_0 = AUDIO_ROW_0 + design.CHANNELS * ROW_PITCH + 14.0
MARGIN = 5.0

# **The two bands are not interleaved, and the first version was.** Twelve rows
# alternating audio and CV put every quad package's body across the rows it does
# not serve: U1 spans four audio rows, which with interleaving means crossing
# three CV rows, and its footprint landed on their resistors. DRC found it 25
# times over. Separate bands cost nothing in area -- the same rows, in two
# groups -- and mean a package only ever crosses rows of its own kind.

# Courtyard boxes, width x height in the footprint's own orientation, read off
# the F.CrtYd outline of each footprint this design names. This table exists so
# that a placement can be iterated in a second rather than in a KiCad round
# trip, which is the same reason floorplan.COURTYARD exists.
#
# **Centrelines, not KiCad's BBox(), and the difference decides a check.**
# GetCourtyard().BBox() comes back 0.09 mm larger in each axis on every
# footprint here -- half a 0.05 mm courtyard line on each side, plus a little
# from polygonising the corners outward. DRC's courtyards_overlap rule compares
# the outlines, so the outlines are what check_overlaps() has to compare: with
# the BBox figures it reports C701 and R901 overlapping by 0.02 mm, on a
# placement KiCad passes, because it counts one courtyard line twice.
# COURTYARD_TOLERANCE_MM below is that 0.09 written down once.
#
# **Every multi-pin entry here used to be transposed, and the word
# "approximate" was carrying it.** The table said it was estimates and that DRC
# was the authority, which is a fair thing to say about a body dimension
# rounded down by a millimetre -- and it was also being used to excuse
# SOIC-14 at (9.2, 6.6) when KiCad's courtyard is 7.49 wide and 9.25 tall. A
# rounded number is approximate. A number on the wrong axis is wrong, and no
# amount of "DRC is the authority" makes a transposed box a conservative one:
# it is smaller than the part in one direction.
#
# It survived because every consumer was transposed too. check_overlaps()
# compares these boxes against each other, so two parts modelled sideways
# collide with each other exactly as they would have upright, and the layout is
# a grid of rows and columns generous enough that the difference never crossed
# a threshold. It surfaced the first time a part had to be fitted into a gap --
# J8, below -- where the model reported a collision that does not exist and
# hid one that does.
#
# The numbers are KiCad's, to two decimals, including the courtyard line width
# that BBox() includes. check_courtyards() in gen_pcb.py is what now holds them
# there: it is the only place both this table and the real footprint exist at
# once.
SIZE = {
    "R_0805": (3.36, 1.90), "C_0805": (3.40, 1.96), "C_1210": (4.60, 3.20),
    "D_SOD-123": (4.70, 2.30), "D_SOD-123F": (4.40, 2.30),
    "SOT-23": (3.86, 3.40), "SOT-523": (2.30, 2.10),
    "Relay_DPDT_Omron_G6S-2F": (10.70, 15.30),
    "SOIC-8": (7.40, 5.40), "SOIC-14": (7.40, 9.16), "SOIC-16": (7.40, 10.40),
    # The supply's four. The first is this repo's own footprint rather than
    # KiCad's -- gen_project.footprint_library() writes it from the datasheet
    # drawing -- and gen_pcb.check_courtyards() is still what holds this row
    # against it, which matters *more* for a generated footprint and not less:
    # two files this repo controls can be wrong together.
    "TRACO_TMR-6-xxxxWI": (22.30, 9.60),
    # The inlet choke, and it is read off KiCad's own courtyard like every
    # other row here -- 10.090 x 6.590 of bounding box, less the 0.045 per
    # edge that is the outline's line width. The four-terminal chokes draw
    # that courtyard as a polyline rather than a rectangle, which turns out
    # not to matter: gen_pcb.check_courtyards() reads BBox() and KiCad builds
    # the polygon from whatever closed outline is on the layer. See
    # design.CHOKE_FP.
    "L_CommonMode_Wuerth_WE-SL2": (10.00, 6.50),
    "TSSOP-20": (7.70, 7.00),
    "TO-252-2": (11.10, 7.00), "Fuse_1206": (4.56, 2.26), "D_SMA": (7.00, 3.50),
    "SOIC-20W": (11.86, 13.30),
    "PinHeader_1x02": (3.54, 6.09), "PinHeader_1x05": (3.54, 13.70),
    "TestPoint": (3.00, 3.00),
}

# Where a footprint's anchor sits inside its own courtyard, in the footprint's
# orientation. Zero for everything KiCad centres on the body, and not zero for
# a pin header, whose anchor is pad 1 at one end -- 5.08 mm for the 1x05, which
# is two thirds of its length. courtyard() centred every part on its position
# and so drew the headers 5 mm north of where they are.
ANCHOR = {"PinHeader_1x02": (0.0, 1.275), "PinHeader_1x05": (0.0, 5.08),
          # Anchored on pad 1, the convention every Converter_DCDC footprint
          # in KiCad uses and therefore the one this one is written to.
          "TRACO_TMR-6-xxxxWI": (8.90, 1.05),
          # The DPAK's tab is pad 2 and the anchor is not the body's middle.
          "TO-252-2": (-0.84, 0.0),
          # The G6S-2F's courtyard is not quite centred on its anchor.
          "Relay_DPDT_Omron_G6S-2F": (0.0, -0.05)}

# How far a box above may sit inside the bounding box KiCad computes for the
# same footprint. Not a fudge factor: it is the courtyard line, measured at
# 0.045 mm per edge on every one of the twelve footprints this design uses, and
# 0.06 is that with a little room. gen_pcb.check_courtyards() is the only place
# both numbers exist at once, and it is what would have caught the transposed
# entries the first time the board was built.
COURTYARD_TOLERANCE_MM = 0.06

# West to east, and the order is floorplan.ZONES' own. Each entry is a column
# of one part per channel; the comment names the zone it implements.
COLUMNS = (
    (r"^J([1-6])$", 6.0, 0, "A0"),           # the loom, on the west edge
    (r"^R([1-6])01$", 13.0, 90, "A1"),
    (r"^R([1-6])02$", 17.0, 90, "A1"),
    (r"^C([1-6])01$", 30.0, 90, "A2"),       # 1210, the wide one
    (r"^R([1-6])11$", 35.0, 90, "A2"),
    (r"^R([1-6])15$", 39.0, 90, "A2"),
    (r"^C([1-6])02$", 43.0, 90, "A2"),
    (r"^R([1-6])21$", 58.0, 90, "A4"),
    (r"^C([1-6])21$", 62.0, 90, "A4"),
    (r"^R([1-6])31$", 76.0, 90, "A4"),
    (r"^C([1-6])31$", 80.0, 90, "A4"),
    (r"^R([1-6])32$", 84.0, 90, "A4"),
    # The CV band: filter west, envelope east.
    (r"^R([1-6])41$", 13.0, 90, "C1"),
    (r"^R([1-6])42$", 17.0, 90, "C1"),
    (r"^R([1-6])43$", 21.0, 90, "C1"),
    (r"^R([1-6])44$", 25.0, 90, "C1"),
    (r"^C([1-6])41$", 29.0, 90, "C1"),
    (r"^C([1-6])42$", 33.0, 90, "C1"),
    (r"^R([1-6])51$", 52.0, 90, "A5"),
    (r"^R([1-6])52$", 56.0, 90, "A5"),
    (r"^D([1-6])51$", 60.0, 90, "A5"),
    (r"^D([1-6])52$", 65.0, 90, "A5"),
    (r"^R([1-6])53$", 70.0, 90, "A5"),
    (r"^R([1-6])54$", 74.0, 90, "A5"),
    (r"^R([1-6])55$", 78.0, 90, "A5"),
    (r"^C([1-6])51$", 82.0, 90, "A5"),
)

# Which rows a column's parts sit on. The audio path is on the odd row of each
# channel and everything else on the even one, so the two never share copper
# with a neighbour's row by accident.
CV_BAND_ZONES = frozenset({"C1", "A5"})

# The packages, each spanning the channels its sections serve. y is the middle
# of that span, computed rather than typed -- move a section in design.SECTIONS
# and the package follows it.
PACKAGE_X = {
    "U1": 23.0, "U2": 23.0,          # front ends, A1
    "U3": 68.0, "U4": 68.0,          # I-V, A4
    "U5": 91.0, "U6": 91.0,          # servo, A4
    "U7": 40.0, "U8": 40.0,          # CV filters, C1
    "U9": 50.0, "U10": 50.0,         # the VCAs, A3
    "U13": 89.0, "U14": 89.0,        # envelope half-wave, A5
}

# The VCAs carry no op-amp sections, so their rows come from design.VCA_CELL.

# The shared block, south of the twelve rows, and **it is arranged around the
# ground split rather than around the parts.** floorplan.py's whole boundary
# argument is that one line separates two return currents and exactly three
# things cross it; the cheapest way to make that true on copper is to put the
# line somewhere straight and keep the straddlers on it.
#
# So: analogue shared parts north of SPLIT_Y, digital south of it, and the four
# parts that genuinely span both -- the '541, the three bypass relays and the
# star R902 -- centred on the line itself.
SHARED_Y = CV_ROW_0 + design.CHANNELS * ROW_PITCH + 10.0
SPLIT_Y = SHARED_Y + 30.0
GROUND_GAP = 2.0

# Zone P, and it is the only block on this board with **two** boundaries
# through it. The ground split at SPLIT_Y separates two returns that meet at
# R902; the isolation barrier separates two returns that meet nowhere, and the
# second is a stronger statement than the first.
#
# So the band is arranged around a vertical line instead of a horizontal one.
# U15 lies along the band with its pins running west to east, primary end
# first, and ISOLATION_X falls in the 5.08 mm gap the package leaves where
# pin 4 is not -- the part's own creepage distance, used as the board's.
# Everything west of that line is referenced to IGND and has **no ground pour
# under it at all**; everything east of it is MDGND like the rest of the
# southern half. gen_pcb.build() pours the southern MDGND as two rectangles
# for exactly this reason, and verify.check_isolation() measures the gap in
# copper rather than trusting the placement.
#
# South of everything else, which is floorplan.py's "far corner from A1 and R"
# read literally: A1 is the north-west column and R crosses the middle, so the
# far corner is the south, and the band costs the board 18 mm of length it has
# plenty of. The switching part of this module is now as far from the front
# ends as the outline allows.
SUPPLY_Y = SPLIT_Y + 39.56             # 197.0, the band's own row
SUPPLY_U15_X = 35.0                    # pad 1, and the pins run east from it
# Between pin 3 and pin 5, which are 5.08 mm apart because pin 4 does not
# exist. Computed rather than typed so that moving the package moves the line.
ISOLATION_X = SUPPLY_U15_X + 3 * 2.54
# The band's northern edge. Nothing referenced to IGND sits north of this, and
# the MDGND pour stops here on the primary's side of ISOLATION_X.
ISOLATION_Y = SUPPLY_Y - 7.0
# The one part that is *meant* to cross the barrier. Declared here as well as
# in design.py because the geometric check and the netlist check are different
# claims, and this repo has been caught before by one instrument covering for
# another.
ISOLATION_BRIDGE = ("C810",)
# How far east of the line a ground stitch has to be pushed to find copper.
# **Not the same number as GROUND_GAP / 2 and that is why it exists.** The pour
# starts one gap east of the line; a via placed exactly there is half its own
# diameter from the fill's edge, and the fill also keeps its clearance from the
# primary tracks running north-south beside it, so what looks like 0.6 mm of
# margin is a via sitting on an island. C810's own stitch was the one that
# found it: DRC reported a 1.6 mm track connected to nothing, which is the
# whole visible symptom of a via that landed 0.6 mm inside a boundary it needed
# to be 3 mm inside.
ISOLATION_STITCH_MM = 3.0

SUPPLY = {
    # -- primary, west of ISOLATION_X, no pour beneath ---------------------
    #
    # **The whole row moved east by 2 mm to fit L801 and the board did not
    # grow.** The choke is 10.09 mm of courtyard and the gap between J8 and
    # D804 was 9.48, so something had to give; what gave is the 3 mm of slack
    # between U15's east edge and R804, which is now 1 mm, plus 2 mm taken out
    # of the secondary's own spacing. The alternative was to grow the band
    # eastwards, which is the one direction that costs board *width* -- the
    # supply band is the south edge, so it is free to grow in y and not in x.
    "J8": (6.0, SUPPLY_Y - 3.0, 0),
    # Immediately at the inlet, ahead of everything else on the primary. See
    # design.supply(): the decoupling has to be on the converter side of it or
    # the choke sees the inlet pair already commoned.
    "L801": (13.0, SUPPLY_Y, 0),
    "D804": (20.0, SUPPLY_Y, 90),
    "C807": (24.5, SUPPLY_Y, 90),
    "C808": (28.5, SUPPLY_Y, 90),
    "C809": (31.5, SUPPLY_Y, 90),
    "U15": (SUPPLY_U15_X, SUPPLY_Y, 0),
    # On the line, and the only thing that is. Offset east by half a pad so
    # that its MDGND end lands inside the pour and its IGND end does not.
    "C810": (ISOLATION_X + 0.6, ISOLATION_Y + 1.5, 0),
    # -- secondary, east of the package ------------------------------------
    "R804": (58.0, SUPPLY_Y, 90),
    "C811": (62.0, SUPPLY_Y, 90),
    "R805": (66.0, SUPPLY_Y, 90),
    "C812": (70.0, SUPPLY_Y, 90),
    "C813": (75.0, SUPPLY_Y, 90),
    "U16": (84.0, SUPPLY_Y, 0),
    "C814": (93.0, SUPPLY_Y, 90),
}

SHARED = {
    # Zone R, the reference and its inverter.
    "U12": (14.0, SHARED_Y, 90),
    "C801": (22.0, SHARED_Y, 90),
    "C802": (26.0, SHARED_Y, 90),
    "C803": (30.0, SHARED_Y, 90),
    "R801": (36.0, SHARED_Y, 90),
    "R802": (40.0, SHARED_Y, 90),
    # At the inverter's own output pin: what D803 clamps is that amplifier, and
    # a long run would clamp the trace instead.
    "D803": (44.0, SHARED_Y, 90),

    # Zone A0, the bond and the one bridge constraint 2 allows.
    "J7": (6.0, SHARED_Y + 10.0, 0),
    "R901": (6.0, SHARED_Y + 16.0, 90),

    # On the line: the two straddling kinds and the module's own star.
    "U11": (20.0, SPLIT_Y, 90),
    # **270, not 90, and it is the one rotation on this board that carries a
    # net each way.** design.py puts MAGND on pin 1 of both stars; at 90
    # degrees pin 1 lands *south* of the split, which is the digital pour, and
    # pin 2 lands north in the analogue one. Both stitch stubs then cross the
    # line to reach their own plane, crossing each other on the way -- the last
    # two DRC violations on the first routed board, and the only ones that were
    # a design fault rather than a router one.
    "R902": (6.0, SPLIT_Y, 270),
    # 90 degrees, so the long axis runs east-west along the split rather
    # than across it: at 0 the body is 15.3 mm tall and reaches both the
    # bypass decoupling row to the north and the pump to the south.
    "K801": (44.0, SPLIT_Y, 90),
    "K802": (62.0, SPLIT_Y, 90),
    "K803": (80.0, SPLIT_Y, 90),

    # Zone F south of the line: the pump, the sink and the flybacks. The coils
    # are north of them at the relays; nothing here carries audio.
    "C805": (40.0, SPLIT_Y + 10.0, 90),
    "D801": (44.0, SPLIT_Y + 10.0, 90),
    "D802": (48.0, SPLIT_Y + 10.0, 90),
    "C806": (52.0, SPLIT_Y + 10.0, 90),
    "R803": (56.0, SPLIT_Y + 10.0, 90),
    "Q801": (60.0, SPLIT_Y + 10.0, 0),
    "D813": (66.0, SPLIT_Y + 10.0, 90),
    "D823": (70.0, SPLIT_Y + 10.0, 90),
    "D833": (74.0, SPLIT_Y + 10.0, 90),

    # **J8 was here, and it moved twice for opposite reasons.** It was filed
    # with J9-J11 as a connector, was found to be a straddler carrying both
    # rails and both grounds, and was moved onto the ground split so that each
    # of its five pins landed in its own pour. It is a two-way *primary* inlet
    # now -- see design.supply() -- so it straddles nothing, and it lives in
    # SUPPLY above with the rest of the isolated side.
    #
    # The mechanism that correction turned on is worth keeping even though the
    # part it applied to is gone, because the next through-hole part in the
    # wrong pour will hit it: stitch_grounds() skips through-hole pads on the
    # correct reasoning that a barrel already crosses every layer, and a
    # barrel reaches the plane that is *under* it. A through-hole pad is
    # already stitched only if it is in its own pour.

    # Zone A6, the envelope ADC. **North of the split and it has to be**:
    # AGND and DGND are both MAGND, so every pad on U17 stitches into the
    # analogue pour, and a package straddling the line would put half of them
    # in the wrong one -- which is the fault J8 was moved for.
    #
    # East of the rail decoupling and south of the reference, which leaves the
    # ENV{n} runs coming down from the CV band into the dividers and the SPI
    # leaving south across the split. The long run is the one on a driven
    # op-amp output; the short one is the 4 kohm source into a switched
    # capacitor. See floorplan.ZONES entry A6.
    # **Rotation 0, and 7 mm of clear board west of it, and both are the
    # router's.** A TSSOP-20 is a 0.65 mm pitch on 0.40 mm pads, so
    # rules.escape_corridor() says there is no legal cell between two of its
    # pins at any class this board could be ordered at -- every pin has to
    # leave the package sideways. At rotation 0 the ten analogue pins face the
    # divider columns and the ten logic pins face away from them, which is the
    # only orientation where those two fans do not have to cross.
    #
    # The first placement had it at rotation 90 with 3.5 mm to the nearest
    # column, and the router left ENVA3, ENVA6 and SCLK unfinished: six nets
    # converging on six pins 0.65 mm apart need somewhere to fan out, and 3.5
    # mm is not it.
    # **The y is 10.21 and not 10.00, and the 0.21 is the routing grid.** A
    # TSSOP's pins are 0.65 mm apart, the router's grid is 0.5, and
    # rules.pad_reach() shows the two are incommensurable: at every phase, two
    # of the ten pin rows contain no grid cell centre at all, so no track can
    # start inside those pads. No placement removes them -- a pad wide enough
    # to always hold a cell would sit closer to its neighbour than this
    # board's own clearance rule allows -- but a placement chooses *which* two
    # rows lose, and this one gives them to AGND/DGND and to CH4/CH7. All four
    # are MAGND, which the router skips because stitch_grounds() has already
    # connected them. See design.ENV_ADC_CHANNEL.
    #
    # **The 45 um window is gone and the 0.21 is kept, and the distinction is
    # worth the two lines.** The window was the phase at which the two pin
    # rows that hold no grid cell landed on AGND/DGND and CH4/CH7 rather than
    # on a routed net, and anything added north of this package moved it. The
    # fan-out removes the constraint entirely -- route.Grid.escape() lays a
    # pad's escape on its own centre line, so a pin row with no cell in it is
    # reached anyway -- so no phase is special any more. The offset stays
    # because moving it would re-route the board for no reason, not because
    # anything depends on it.
    "U17": (70.0, SHARED_Y + 10.21, 0),
    # The three locals, each at the pin it serves: AVDD, DVDD, REFIN+. **All
    # three north of the package, and the third one moved there for a reason
    # the router found.** C819 was south, which put its run to REFIN+ -- pin 4,
    # near the north end of the west row -- straight up through the channel
    # fan, in the 3.25 mm of pin row the six ENVA{n} nets are already
    # converging into. ENVA1 and ENVA2 were what would not finish. The west
    # row arrives in order from the north now: AVDD, REFIN+, then the
    # channels, and nothing crosses anything.
    "C817": (68.0, SHARED_Y + 3.5, 90),
    "C818": (72.0, SHARED_Y + 3.5, 90),
    "C819": (76.0, SHARED_Y + 3.5, 90),
    # The rail, east of everything: its two nets are V5 and V3V3 and neither
    # of them belongs in the fan.
    "U18": (84.0, SHARED_Y + 10.0, 0),
    "C815": (84.0, SHARED_Y + 3.5, 90),
    "C816": (84.0, SHARED_Y + 16.5, 90),

    # Zone D2, the signal connectors, on the south edge where a loom can reach
    # them.
    "J9": (26.0, SPLIT_Y + 18.0, 0),
    "J10": (42.0, SPLIT_Y + 18.0, 0),
    "J11": (58.0, SPLIT_Y + 18.0, 0),
    # The ADC's own two, on the same edge as the other three so the loom is
    # one bundle -- but **west of J10 rather than east of J11**, and that is a
    # routing fact rather than a tidy one. The three bypass relays sit across
    # the ground split on 18 mm centres and are 15.3 mm wide, so the gaps
    # between them are 2.7 mm; the one wide corridor through that row is the
    # 9.7 mm between U11 and K801. Six SPI nets have to get from U17 to these
    # connectors, and putting them east meant threading that row at 2.7 mm.
    # SCLK was one of the three nets the router could not finish.
    "J12": (31.0, SPLIT_Y + 18.0, 0),
    "J13": (36.0, SPLIT_Y + 18.0, 0),
}

# The ADC's six input networks: three columns of one part per channel, on
# their own row pitch rather than the board's 7.62 mm one. They are per-channel
# parts in a shared block, which is a shape COLUMNS cannot express -- COLUMNS
# rows are the twelve of the two bands -- so they get their own rule in
# position() and their own constants here.
ADC_INPUT_X = ((r"^R([1-6])56$", 50.0), (r"^R([1-6])57$", 54.0),
               (r"^C([1-6])52$", 58.0))
ADC_ROW_0 = SHARED_Y
# 3.6 mm and not 4.0: an 0805 on its side is 3.36 mm of courtyard, so this is
# 0.24 mm of clearance between rows and it takes 2 mm out of the vertical
# spread the six ENVA{n} nets have to fan across. The fan is the one congested
# thing in this block -- six tracks from a 18 mm column into 3.25 mm of pin
# row -- and every millimetre of spread removed is one it does not have to
# turn through.
ADC_ROW_PITCH = 3.6

# The pull-downs sit at the controller connector, which is where their whole
# argument is: a hi-Z MCU has to read as a defined low at the pin it left.
PULLDOWN_X = 74.0
PULLDOWN_Y = SPLIT_Y + 18.0

# Designators that have to move, with the reason each one does. The mixer keeps
# the same table and for the same cause: KiCad puts a reference above the body,
# which after a 90-degree rotation is *west* of it, and west of the VCAs is the
# stability capacitor 7 mm away. Six DRC violations, all of them one text field
# on two pads.
# **U15's is not the same kind of collision and it is worth the distinction.**
# The VCAs' reference lands on a neighbour because a 90-degree rotation puts
# KiCad's above-the-body text to the west. U15 is not rotated: its reference is
# where the footprint puts it, above its own body, and what is there is C810 --
# which has to be there, because it is the one part that sits on the isolation
# line. So this move is the barrier's cost in silkscreen, and moving the
# capacitor instead would be moving the thing that is placed for a reason.
REFERENCE_MOVES = {"U9": (8.0, 0.0), "U10": (8.0, 0.0), "U15": (0.0, -4.0)}

# **Empty, and that is the whole of choosing the last two parts.** This held a
# 14 x 9 mm envelope for each of the three bypass relays, because
# design.BYPASS_RELAY was None and an unchosen part still needs its area
# committed. The G6S-2F is 10.70 x 15.30, so the guess was 1 mm out in one axis
# and 6 mm out in the other -- turned 90 degrees it is 15.30 wide, and the
# three still clear each other on the 18 mm spacing below because the guess was
# wrong in the direction that had room.
RESERVED = {}

# Rail decoupling, two rows of twelve rather than one of twenty-four: a single
# row is 84 mm long and would set the board's width on its own.
BYPASS_X = 8.0
BYPASS_Y = SHARED_Y + 16.0


def row(n, cv=False):
    """The y of channel n's row, in the audio band or the CV/envelope band."""
    return (CV_ROW_0 if cv else AUDIO_ROW_0) + (n - 1) * ROW_PITCH


CV_ROLES = frozenset({"cv", "env_a", "env_b"})


def _package_rows(ref):
    """Every row a package's sections reach, as y values.

    Per *section*, not per channel, and that distinction is a bug this file
    already had: U6 carries servos 5 and 6 in the audio band and envelope
    summing stages 5 and 6 in the CV band, so a channel-keyed lookup saw
    channel 5 twice and kept whichever answer it read last. The package landed
    in the CV band and left its servos 60 mm away.

    A package that genuinely serves both bands -- U2, U4 and U6 do, because
    their spare sections took the envelope summing stages -- lands between
    them, which is where a part belonging to both belongs. That is the
    placement cost of filling those sections, and the alternative was two more
    OPA1644.
    """
    # "spare" is excluded, and it is not a detail: SECTIONS keys spare
    # sections (role, index), so U14's two terminated followers read as
    # channels 1 and 2 and dragged the package into the audio band -- a
    # placement decided by a loop counter. A spare has no channel, which is
    # what makes it spare.
    rows = [row(n, role in CV_ROLES)
            for (role, n), (pkg, _) in design.SECTIONS.items()
            if pkg == ref and role != "spare" and isinstance(n, int)
            and 1 <= n <= design.CHANNELS]
    rows += [row(n) for n, (pkg, _) in design.VCA_CELL.items() if pkg == ref]
    return sorted(rows)


def position(ref):
    """(x, y, rotation) for one reference, or None if nothing claims it."""
    for pattern, x, rotation, zone in COLUMNS:
        found = re.match(pattern, ref)
        if found:
            return (x, row(int(found.group(1)), zone in CV_BAND_ZONES),
                    rotation)

    if ref in PACKAGE_X:
        rows = _package_rows(ref)
        if not rows:                      # nothing per-channel: shared only
            return (PACKAGE_X[ref], row(3), 90)
        # **A package that reaches both bands goes in the gap between them,
        # not at the average of its rows.** The average is inside one band or
        # the other, on a row it does not serve, and it lands on that row's
        # parts -- which is what U4 and U6 did. The gap is 21.6 mm and a
        # SOIC-14 on its side is 9.2, so the middle of it clears both.
        if rows[0] < CV_ROW_0 <= rows[-1]:
            top = row(design.CHANNELS)
            return (PACKAGE_X[ref], round((top + CV_ROW_0) / 2, 2), 90)
        return (PACKAGE_X[ref], round((rows[0] + rows[-1]) / 2, 2), 90)

    if ref in SHARED:
        return SHARED[ref]

    if ref in SUPPLY:
        return SUPPLY[ref]

    for pattern, x in ADC_INPUT_X:
        found = re.match(pattern, ref)
        if found:
            return (x, ADC_ROW_0 + (int(found.group(1)) - 1) * ADC_ROW_PITCH,
                    90)

    found = re.match(r"^R81([1-6])$", ref)
    if found:
        return (PULLDOWN_X + 4.0 * (int(found.group(1)) - 1), PULLDOWN_Y, 90)

    found = re.match(r"^C7(\d\d)$", ref)
    if found:
        index = int(found.group(1)) - 1
        return (BYPASS_X + 3.5 * (index % 12),
                BYPASS_Y + 4.0 * (index // 12), 90)

    return None


def outline():
    """The board rectangle this placement implies, from SIZE alone.

    gen_pcb.py computes the same thing from the footprints KiCad actually
    loads, and the two agreeing is worth something: it means this file can be
    reasoned about without KiCad, which is the reason it exists.
    """
    boxes = [courtyard(ref) for ref in sorted(design.PARTS)]
    boxes = [box for box in boxes if box]
    return (round(min(b[0] for b in boxes) - MARGIN, 2),
            round(min(b[1] for b in boxes) - MARGIN, 2),
            round(max(b[2] for b in boxes) + MARGIN, 2),
            round(max(b[3] for b in boxes) + MARGIN, 2))


def area():
    left, top, right, bottom = outline()
    return (right - left) * (bottom - top)


def extents(courtyards):
    """The board outline the placement implies, plus a margin.

    Derived rather than declared: a rectangle typed in by hand is a rectangle
    that stops being true the first time a part moves, and this repo has spent
    two passes on the consequences of exactly that in floorplan.py.
    """
    xs = [x for x, y, w, h in courtyards]
    ys = [y for x, y, w, h in courtyards]
    right = max(x + w / 2 for x, y, w, h in courtyards)
    bottom = max(y + h / 2 for x, y, w, h in courtyards)
    left = min(x - w / 2 for x, y, w, h in courtyards)
    top = min(y - h / 2 for x, y, w, h in courtyards)
    return (round(left - MARGIN, 2), round(top - MARGIN, 2),
            round(right + MARGIN, 2), round(bottom + MARGIN, 2))


def check_placed():
    """Every part has a position, and an unmatched reference is an error."""
    return [f"{ref} has no position in placement.py -- add it to a column, to "
            f"SHARED, or say why it is not on the board"
            for ref in sorted(design.PARTS) if position(ref) is None]


def courtyard(ref):
    """(left, top, right, bottom) for one part, from SIZE, ANCHOR and rotation.

    `position()` gives the *anchor*, which is what gen_pcb.py hands
    SetPosition(), and for most footprints that is the middle of the body. For
    a pin header it is pad 1, so the box has to be offset -- and the offset
    turns with the part. KiCad's convention, measured rather than assumed:
    local (x, y) at angle a lands at (x cos a + y sin a, -x sin a + y cos a),
    so pad 3 of a 1x05 at local (0, 5.08) is at (+5.08, 0) when the part is
    rotated 90 and (-5.08, 0) at 270.
    """
    spot = position(ref)
    if spot is None:
        return None
    x, y, rotation = spot
    footprint = design.PARTS[ref].footprint
    offset = (0.0, 0.0)
    if footprint is None:
        width, height = RESERVED.get(ref, (14.0, 9.0))
    else:
        # **Longest token first, and that is not tidiness.** These are substring
        # matches, and "D_SOD-123" is a substring of "D_SOD-123F" -- so with
        # plain dict order the low-drop clamp at D803 would silently be
        # measured as the 0.3 mm wider package it replaced, and the only thing
        # that would ever have said so is gen_pcb.check_courtyards(). Matching
        # the most specific token means the table can gain a variant without
        # its position in the dict becoming load-bearing.
        for token in sorted(SIZE, key=len, reverse=True):
            if token in footprint:
                width, height = SIZE[token]
                offset = ANCHOR.get(token, (0.0, 0.0))
                break
        else:
            return None
    radians = math.radians(rotation)
    cosine, sine = math.cos(radians), math.sin(radians)
    centre_x = x + offset[0] * cosine + offset[1] * sine
    centre_y = y - offset[0] * sine + offset[1] * cosine
    if rotation % 180:
        width, height = height, width
    return (centre_x - width / 2, centre_y - height / 2,
            centre_x + width / 2, centre_y + height / 2)


def check_overlaps():
    """No two courtyards overlap, against the estimates in SIZE."""
    problems = []
    boxes = [(ref, courtyard(ref)) for ref in sorted(design.PARTS)]
    boxes = [(ref, box) for ref, box in boxes if box]
    for index, (ref, box) in enumerate(boxes):
        for other, box2 in boxes[index + 1:]:
            if (box[0] < box2[2] and box2[0] < box[2]
                    and box[1] < box2[3] and box2[1] < box[3]):
                problems.append(
                    f"{ref} and {other} overlap: "
                    f"{tuple(round(v, 1) for v in box)} against "
                    f"{tuple(round(v, 1) for v in box2)}")
    return problems


def check_zones():
    """Every column's parts are in the ground domain its zone declares.

    The check that ties this file to floorplan.py rather than leaving them to
    agree by good intentions. A column that implements zone A5 must contain
    parts floorplan.DOMAINS puts in the analogue domain; if somebody moves a
    part between blocks in design.py and not here, the two disagree and this
    says which.
    """
    problems = []
    domains = {tag: domain for tag, _, domain, _, _ in floorplan.ZONES}
    for pattern, _, _, zone in COLUMNS:
        if zone not in domains:
            problems.append(f"column {pattern} names zone {zone}, which is not "
                            f"in floorplan.ZONES")
            continue
        for ref in sorted(design.PARTS):
            if not re.match(pattern, ref):
                continue
            actual = floorplan.domain_of(ref)
            if domains[zone] != "STRADDLE" and actual != domains[zone]:
                problems.append(
                    f"{ref} is placed in zone {zone} ({domains[zone]}) and "
                    f"floorplan.py puts it on {actual}")
    return problems


def main():
    print("placement")
    problems = check_placed() + check_zones() + check_overlaps()
    print(f"  every part has a position              "
          f"{'ok' if not check_placed() else 'FAIL'}")
    print(f"  columns agree with floorplan zones     "
          f"{'ok' if not check_zones() else 'FAIL'}")
    overlaps = check_overlaps()
    print(f"  no two courtyards overlap              "
          f"{'ok' if not overlaps else str(len(overlaps)) + ' FAIL'}")
    for problem in problems[:12]:
        print(f"      {problem}")
    if len(problems) > 12:
        print(f"      ... and {len(problems) - 12} more")
    left, top, right, bottom = outline()
    print(f"  {len(design.PARTS)} parts, {design.CHANNELS} rows per band on a "
          f"{ROW_PITCH} mm pitch, shared block at y = {SHARED_Y:.1f}")
    print(f"  outline {right - left:.1f} x {bottom - top:.1f} mm = "
          f"{area():.0f} mm2")
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
