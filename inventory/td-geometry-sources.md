# WP-08 Thermal Desktop geometry and physics sources

Checked online and through public repository history on 2026-11-13 and 2026-11-14 against the [geometry support matrix](../docs/td-sinda.md) and
[WP-08 acceptance evidence](../plans/evidence/WP-08.json). The inventory records
public filenames, immutable upstream locations and read-only observations.
Active class counts come from object records matched to the DWG class table.
The results support decoder and integration work. Geometry regeneration and
solver comparisons still require source exports or a licensed reference run.

## Verified vendor downloads

Ansys publishes these OpenTD demo archives through its
[current downloads](https://developer.synopsys.com/docs/thermal-desktop) and
[previous downloads](https://developer.synopsys.com/docs/thermal-desktop/previous)
pages. All four archive downloads matched their pinned upstream Git blobs.

| Archive | Contents relevant to WP-08 | SHA-256 |
| --- | --- | --- |
| [2026R1-Net4.zip](https://github.com/ansys/DevRelPublic/blob/74a15b6e2c9da75fb8b3bff99ad5e88f5038a99f/Downloads/Thermal-Desktop-OpenTD/2026R1-Net4.zip) | Ten unique AC1032 drawings under `2026R1-Net4/model/` and identical duplicates under `2026R1-Net4/bin/Debug/x64/model/`. Includes properties, solver inputs and results. | `f89b40ed48412e40bafa004261e23d115088f48941ff87118a4f0045a057252c` |
| [2024 R2 OpenTDv242Demos01.zip](https://github.com/ansys/DevRelPublic/blob/74a15b6e2c9da75fb8b3bff99ad5e88f5038a99f/Downloads/Thermal-Desktop-OpenTD/2024R2/OpenTDv242Demos01.zip) | The same ten drawings under `model/`. Each DWG matches its 2026 R1 archive copies byte for byte. Use one copy per drawing. | `e2d589b13040e170ff9b4d39df15013aae59ffb46a9e06db1111a3c5e728ee87` |
| [2025R2-Net4.zip](https://github.com/ansys/DevRelPublic/blob/74a15b6e2c9da75fb8b3bff99ad5e88f5038a99f/Downloads/Thermal-Desktop-OpenTD/2025R2-Net4.zip) | C# demo source, SINDA input decks and 17 SAV files. Zero DWG, TDP or RCO members. | `d6520c75a6e6285c0251126fd047cbd8bc8de970a0ab26bdc97b47d6283e82bb` |
| [92.0.0.0 OpenTDv92000-Demos01.zip](https://github.com/ansys/DevRelPublic/blob/74a15b6e2c9da75fb8b3bff99ad5e88f5038a99f/Downloads/Thermal-Desktop-OpenTD/92.0.0.0/OpenTDv92000-Demos01.zip) | C# demo source, SINDA input decks and 17 SAV files. Zero DWG, TDP or RCO members. | `6523156c80e4caf575e346f6c52cd44bc7b9b9b60f313aa1c4fe41afba480f76` |
| [2027 R1 OpenTD2027R1Demos01.zip](https://github.com/ansys/DevRelPublic/blob/efc18d7c7b303696069e0dbeee3a40beb357c15c/Downloads/Thermal-Desktop-OpenTD/2027.R1.SP00/OpenTD2027R1Demos01.zip) | Public development branch. Verified all 11 AC1032 DWG members. Ten are byte-identical to the corresponding 2024 R2 drawings. The eleventh, `model/reducedModelDemo_reduced.dwg`, duplicates `model/reducedModelDemo.dwg`. There are zero new DWG byte streams and zero active `RcPolygon`, legacy linear FE, quadratic-solid or `TdMesherVA` instances. | `2083787ac70018c82e78dc546d5c94039d43a3ff7e8dbc671a7544c0586e1bb7` |

The following member paths are relative to `model/` in the 2024 R2 archive.
AC1032 identifies the DWG container. The Thermal Desktop writer release and
patch for the ten drawings are unverified.

| Drawing | Observed active classes and companions |
| --- | --- |
| `Compartment.dwg` | One `TdMesher`, 2,296 `RcLinearTri2`, 6,557 `RcLinearTet2` and 1,148 `RcLinearWedge2`. The archive also includes `Compartments.rco` and `Compartments.tdp`. |
| `SatelliteConfigurator.dwg` | One `TdMesher`, five linear FE topologies (triangle, quadrilateral, tetrahedron, wedge and brick), rectangles, an FD brick, an FD cylinder and an FD cone. Also acquire `SatelliteConfigurator.rco` and `SatelliteConfigurator.tdp`. |
| `captureScreenshotsDemo.dwg` | Three cones, four cylinders, two spheres, three disks, 21 rectangles and 24 `RcMeshFD` objects with DXF name `RCMESHFD`. FCST decodes the marker-56 surfaces and polygon meshes and exports their static boundaries. |
| `Contours.dwg` | One rectangle, two FD bricks, two FD spheres and one FD cylinder. The archive includes `Contours.rco`, `Contours.tdp` and `contours.sav`. `ContourFinder/ContourFinderDialog.cs` references the DWG and SAV. |
| `QFlowPlotterModel.dwg` | Rectangles, FD bricks, FD cylinders and disks. The archive includes `qflowplotter.rco`, `qflowplotter.tdp` and `qflowplotter.sav`. `QFlowPlotter/QFlowPlotterDialog.cs` references the DWG and SAV. |
| `exploringResults.dwg` | Seven rectangles and two FD bricks. The separate `exploringResultsSav/` suite provides result-reader samples including `steady.sav`, `hot_beta0.sav` and `comparer/baseline.sav`. Verify each case association before using it for parity. |
| `UDFA.dwg` | 3,225 `RcLinearTri2` records. The archive includes `UDFA.tdp`. |
| `organizeModelWithLinq.dwg` | 128 rectangles. |
| `common.dwg`, `reducedModelDemo.dwg` | Zero active classes from the current WP-08 geometry catalog. |

The vendor FE, mesh and curved-solid examples exercise several wire layouts.
The reader covers the observed marker-56 records and stored mesh links.
Mesh regeneration remains open. The archives also include standalone
SINDA/FLUINT examples under `model/controlSindaFluint/` (`control.inp`,
`control.cc`, `justRun.inp`, `justRun.cc`). Use those for the deck path.
Their relationship to any DWG must be established separately.

The seven public commits affecting the [OpenTD downloads directory on main](https://github.com/ansys/DevRelPublic/commits/main/Downloads/Thermal-Desktop-OpenTD)
add no distinct demo archive beyond the four main-branch downloads above. The older
`2024R2/OpenTD_92_0_0_0_Demos01.zip` has the same Git blob as
`92.0.0.0/OpenTDv92000-Demos01.zip`. One additional historical ZIP is an
HTML API class reference. The public [ModelCenter plug-in example ZIP](https://ansyshelp.ansys.com/public/Views/Secured/Doc_Assets/Static/ModelCenter_Plugins_example_files.zip)
contains CATIA and MATLAB examples and zero DWG or Thermal Desktop project
members.

### Original Thermal Desktop installation samples

These files were present in the vendor sample installation associated with
Thermal Desktop 6.3.022. Paths below are relative to the installation's
shared Thermal Desktop sample directory. The installer version identifies the
distribution. The original drawing writer builds remain unverified.
[CRTech 6.3 installation guide](https://www.crtech.com/sites/default/files/files/Install_instructions/TD_Suite_Install_63.pdf)

| Sample | Exact files and verified contents |
| --- | --- |
| `ANSYS CoSolver/Heating Coil Steady v221/` and `ANSYS CoSolver/Heating Coil Transient v221/` | Each contains `CRTech/HeatingCoil.dwg`, `CRTech/System.scdoc`, `CRTech/Container.scdoc`, `CRTech/HeatingCoil.scdoc`, `CRTech/rcoptics.rco`, `CRTech/tdthermo.tdp` and `CRTech/crtech.scp`. Both AC1032 DWGs contain two `TdScImporter` records, one `TdFiniteElementMeshImporter`, one heat load and 12,900 linear elements each (100 triangles, 2,800 quads and 10,000 wedges). FCST decodes the elements and heat loads and resolves links to the stored mesh. The supplied CAD files can seed a future synchronization test. |
| Heating Coil coupling files | Both cases include `SyC/Settings.h5` and `Fluent/fluent.scp`. The steady mesh is `Fluent/HeatingCoil.cas.h5` and the transient mesh is `Fluent/HeatingCoilFLUENTMesh.cas.h5`. The transient `CRTech/` directory also contains `CouplingRegions.txt`, `Convection_Coefficients.txt`, `Fluid_Temperatures.txt` and `HeatRate.txt`. These are candidates for checking coupling-region and load mappings. The vendor workshop describes the data-exchange setup. A fresh licensed run is needed to verify solver results. [CRTech workshop slides](https://tfaws.nasa.gov/wp-content/uploads/TFAWS2020-CRTech-CHT.pdf) |
| `TDDirect/TDD_Test_Drawing.dwg`, `TDDirect/TDD_Block.scdoc` | The original installed DWG is byte-identical to the CMU Argus copy below. The installed SCDOC differs in bytes from the public copy. Preserve the provenance of both companion variants when testing. |
| `beercan.dwg`, `thermal_SI.dwg` and `TdThermo.tdp` | The installed Beer Can is byte-distinct from the UC Davis tutorial copy and has the same FE class counts. Its disk and four linear FE classes decode. The SI template is AC1027 and has no active WP-08 geometry classes. |

The five installed drawings yielded no active instances of the outstanding
conic, quadratic, legacy FE, polygon or `TdMesherVa` classes. The two coil
drawings provide AC1032 importer coverage candidates and are available with
the vendor installation for local work.

## Verified public community files

| Source | Exact files and WP-08 use |
| --- | --- |
| CMU Argus TD Direct test | [`TDD_Test_Drawing.dwg`](https://github.com/cmu-argus/Thermal/blob/66e37cc0bfb4a1b5b8a9489e6bd4f9b4ec8d5877/TDD_Test_Drawing.dwg) and [`TDD_Block.scdoc`](https://github.com/cmu-argus/Thermal/blob/66e37cc0bfb4a1b5b8a9489e6bd4f9b4ec8d5877/TDD_Block.scdoc). The AC1027 drawing opens in the independent adapter. All 52 linear triangles and 54 linear tetrahedra resolve their source nodes and export boundaries. The importer link reader resolves the SpaceClaim companion and the generated elements. Capture a fresh sync and connectivity export to test regeneration. |
| UC Davis FE conduction and radiation | [`FEconductandRad-Completed.zip`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/6.%20FE_CondRad_63/FEconductandRad-Completed.zip) contains `FEconductandRad-Completed/fe1.dwg`, `RcOptics.rco` and `TdThermo.tdp` in the same member directory. The current decoder reads 220 linear quads and 168 linear bricks. |
| UC Davis Beer Can | [`BeerCan-Completed.zip`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/5.%20BeerCan_63/BeerCan-Completed.zip) contains `BeerCan-Completed/beercan.dwg`, `RcOptics.rco` and `TdThermo.tdp`. The decoder reads one disk, eight linear triangles, 40 quads, 32 wedges and 32 bricks. The [vendor install guide](https://www.crtech.com/sites/default/files/files/Install_instructions/ThermalDesktopInstall_licensed.pdf) also documents a `beercan.dwg` test model. |
| UC Davis mesh mapping | [`MappingResults-Complete.zip`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/7.%20MappingResults_63/MappingResults-Complete.zip) contains `MappingResults-Complete/coarse.dwg`, `coarse_quad.NAS`, `fine_quad.NAS`, `RcOptics.rco` and `TdThermo.tdp`. The drawing contains 103 decodable linear quads. The two Nastran meshes give independent connectivity inputs for mapping checks. |
| UC Davis contact and thermal examples | [`Contactor-Completed.zip`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/8.%20Contactor_63/Contactor-Completed.zip) contains `Contactor-Completed/Contactor.dwg` and `TdThermo.tdp`. [`DynamicSinda-Complete.zip`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/10.%20DynamicSindaRadCAD_63/DynamicSinda-Complete.zip) contains `DynamicSinda-Complete/dynamic.dwg`, `RcOptics.rco` and `TdThermo.tdp`. The former has disks, a cylinder, a brick and a rectangle. The latter has seven rectangles, a cylinder and two disks. Both are candidates for checking geometry-attached physics after a reference run. |
| UC Davis transient and version leads | [`11. TransientDLC_61/Transient/`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/tree/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/CRTech%20Tutorials/11.%20TransientDLC_61/Transient) has `barDemo-01.dwg`, `RcOptics.rco` and `TdThermo.tdp` in both the starting directory and `completed/`. Each drawing has one decodable FD brick. [`ThermalDesktop63Patch22_Thermal_Template.dwg`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Reference%20Files%20and%20Tutorials/ThermalDesktop63Patch22_Thermal_Template.dwg) is labeled in the filename and has no active catalog geometry. The folder and filename labels do not establish the save build. |
| pyopentd example and results | [`sample/td_model/`](https://github.com/nishitomo206/pyopentd/tree/70aac5572bdf1b48d04dfcdb70838493df947ef7/sample/td_model) contains `sample.dwg`, `RcOptics.rco` and `TdThermo.tdp`. The [sample notebook](https://github.com/nishitomo206/pyopentd/blob/70aac5572bdf1b48d04dfcdb70838493df947ef7/sample/sample.ipynb) opens that DWG, runs a case and exports temperature and heat-rate data to [`sample/sample_output.csv`](https://github.com/nishitomo206/pyopentd/blob/70aac5572bdf1b48d04dfcdb70838493df947ef7/sample/sample_output.csv). The CSV has 85 rows and 161 columns. The DWG has six FD bricks, one cylinder and two disks whose records hit unsupported filer or surface revisions. The notebook establishes the intended association. Reproducing its run remains necessary for numerical acceptance. |
| pyopentd fork drawing | The fork's [`sample.dwg`](https://github.com/kai0722/pyopentd/blob/666c3b029b537ab1b6b5bc29d4791d859ec3f285/sample/td_model/sample.dwg) is a distinct 88,063-byte AC1032 drawing. Git blob `0708d6717b24767977678c408fe01babbe601c6d`, SHA-256 `404c129dcd68d7816ecf07e1f917abfa11d65f28ebbd2e06f55236bdb3658237`. It has 75 nodes, six FD bricks, two disks and one cylinder. The active-class scan found zero legacy linear FE, quadratic-solid, `RcPolygon`, `TdMesherVA` or CAD importer records. The fork's `ThermalDesktop62Patch14_sample.dwg` matches the upstream `sample.dwg` Git blob. Its filename gives a version lead for that file. The distinct fork drawing's writer build and association with the upstream CSV remain unverified. |

The selected university and pyopentd files matched pinned upstream Git blobs.
The two Nastran decks contain 103 and 260 `CQUAD4` elements, respectively.
The CMU DWG and SCDOC SHA-256 values are
`b7f5070d9d03469e01132294c9e71423dc7ef5011c6637e84666cda9556b23f1` and
`a186b66d4132d9a55dc9b670136d7ccd9ebdd1c01fa92ff61fbae90741029290`,
respectively. The UC Davis tree also contains template, circuit-board, laminate
and parameterized-box tutorials. The downloaded examples in those groups add
rectangle and property cases. The existing Artemis model and UC Davis SINDA
deck remain indexed in the [WP-01 source inventory](README.md).

### UC Davis drawing, decks and saved results

The [historical UC Davis case directory](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/tree/e9260fb16719330a635439b12100e9cf2788904e/Working%20CubseSAT%20Model) contains the following files at one commit. Downloads matched the upstream Git blobs.

| Files | Verified observation and use |
| --- | --- |
| `CubeSat.dwg`, `OpticalDataCustom.rco`, `ThermalData.tdp`, `ThermalDataFilled.tdp` | The drawing is AC1032 and contains eight rectangles, one disk, one heat load and one orbit. Candidate for FD surface numbering, heat-load and orbit bindings. Confirm which TDP the DWG uses when reopening. |
| `case1.inp`, `case2.inp`, `case3.inp` and corresponding `.cc`, `.out` and `.sav` files | All three `.cc` files identify Thermal Desktop 6.3. For each case number `n`, the entry deck references `case<n>.cc`, `C<n>A0.hra`, `C<n>A0.hrl`, `C<n>A1.k_in` and `C<n>A2.k_in`. Every direct reference was retrieved. Validate runtime dependencies and compare case and node identities across DWG, decks and results before numerical acceptance. |
| `CubeSat_6_60.dwg`, `CubeSat.bak` | The former is AC1027 with seven rectangles and one disk. The backup is AC1032 with eight rectangles and one disk. They provide two container cases. The file names and signatures leave the exact writer build unverified. |

The [later archived directory](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/tree/c7424e7e9be0b40527c69f84800ef6c691fc73dc/OLD_Working%20CubseSAT%20Model) preserves the same drawing and case blobs. The [working directory at that commit](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/tree/c7424e7e9be0b40527c69f84800ef6c691fc73dc/Working%20CubeSat%20Model) has different drawing, property and `case1` bytes. Use a single pinned directory when assembling a case. The oldest [`CubeSat.dwg`](https://github.com/Space-and-Satellite-Systems-UC-Davis/Structure-Thermal-Desktop/blob/01a2a630e99103cecc00ec2c82dce9ae7e163479/CubeSat.dwg) contains seven rectangles and one disk.

The follow-up class check covered 23 additional distinct DWG byte streams,
including the historical backup. It yielded no active ogive, scarfed surface,
solid ellipsoid, quadratic element, older FE or polygon class, or `TdMesherVa`
instance. The AC1027 UC Davis model adds a container case for simpler FD geometry.

### HSFL Artemis drawing history

The two public commits touching the [Artemis thermal directory](https://github.com/hsfl/artemis-hardware/commits/bcc649cf7932dcc410f8a594213383fb84e68d47/Thermal/)
preserve the same DWG and backup blobs. The separately acquired
[`artemis_thermal_lab.bak`](https://github.com/hsfl/artemis-hardware/blob/bcc649cf7932dcc410f8a594213383fb84e68d47/Thermal/artemis_thermal_lab.bak)
is a distinct 259,773-byte AC1032 drawing with 918 `RcNode` records, 16
`RcRectangle` records and two `RcFdBrick` records. The active-class scan found
zero legacy or quadratic FE classes, `RcPolygon`, `TdMesherVa` or mesh importers.
Its Git blob is `e268da964685b87940bbd256ef7282c32dc91904` and its SHA-256 is
`47fdc2180a1d4f44367576d7700f19ca81a2f726a8df9ca991fd3c85f28ab343`.
The backup and the baseline drawing lack a documented mesh regeneration
sequence. The repository also carries CAD lock files, which were excluded.

### NASA GSFC course drawings and postprocessed results

The [NASA course record](https://ntrs.nasa.gov/citations/20220017174) distributes
`(reupload) HP Thermal Analysis Presentation.pptx`. The original PowerPoint
contains `Sample_Model_Files.zip` in `ppt/embeddings/oleObject1.bin`, in the
`Ole10Native` stream. Retrieve the original PPTX and extract the embedded ZIP
without launching the OLE object. The embedded ZIP SHA-256 is
`20cdd88ab8acf6ece10caba61ab0b92e5ce035de6b46bde42e0a3b8f18a07626`.

| Exact member files | Verified observation and use |
| --- | --- |
| `Sample_Model_CAD.dwg` | AC1032 starter drawing with no active WP-08 catalog geometry classes. Use as the CAD input for the course sequence. The slide instructions use the shorter name `Sample_CAD.dwg`. |
| `Sample_Instruments.dwg`, `Sample_Instruments.rco`, `Sample_Instruments.tdp` | AC1032 instrument drawing with 24 linear quadrilaterals, six linear triangles, 33 rectangles, one cylinder and three disks. Use with the two property files to check FE and FD geometry side by side. |
| `Sample_Model_Final.dwg`, `Sample_Model_Final.rco`, `Sample_Model_Final.tdp` | AC1032 completed drawing with 320 linear quadrilaterals, 32 linear triangles, 57 rectangles, 10 disks, eight cylinders, eight spheres, three FD cylinders, 18 heat loads and 14 orbits. Candidate for mixed FE/FD case bindings and geometry-attached physics. |
| `HeaterSummary.xls`, `PostProcessed_Initial.xlsx`, `PostProcessed_Final.xlsx` | Heater summary and two postprocessed workbooks. Each XLSX has 23 worksheets. Verify case, run and node identities before using workbook data for numerical acceptance. The embedded archive contains no generated SINDA deck or SAV file. |

The NASA drawings add mixed geometry and load examples. The read-only count
found no active quadratic or older FE class and no held conic or mesher class
in these three drawings.

## Downloaded inputs for generating and checking reference fixtures

The inputs below provide geometry, connectivity or independent physics checks.
Thermal Desktop must write the corresponding DWGs to establish the native
class identity, node order and payload layout.

| Input | Use |
| --- | --- |
| [Kitware `clipQuadraticCells.py`](https://github.com/Kitware/VTK/blob/03b591fa9af596b58a474057fb6b39da6d3941e1/Filters/General/Testing/Python/clipQuadraticCells.py) and [`ExtractEdgesQuadraticCells.py`](https://github.com/Kitware/VTK/blob/03b591fa9af596b58a474057fb6b39da6d3941e1/Filters/Extraction/Testing/Python/ExtractEdgesQuadraticCells.py) | Both instantiate quadratic triangle, quad, tetrahedron, wedge, pyramid and brick with explicit points and connectivity. Use the coordinates to seed the six TD cases and use VTK independently to check curved edges and faces after mapping node order. Source inspected without executing it. |
| [Abaqus steady heat-transfer patch test](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEVERRefMap/simaver-c-heattranspatch.htm) | Downloaded and checked `ec26dfp4.inp` (DC2D6 triangle), `ec28dfp4.inp` (DC2D8 quad), `ec3adfp4.inp` (DC3D10 tet), `ec3fdfp4.inp` (DC3D15 wedge), and `ec3kdfp4.inp` (DC3D20 brick). The prescribed linear temperature field gives a constant-flux reference. Use VTK for the 13-node pyramid geometry. |
| [Abaqus NAFEMS T3 transient benchmark](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEBMKRefMap/simabmk-c-t3.htm) | Downloaded and checked `nt3xx26f.inp` and `nt3xx28f.inp` for DC2D6 and DC2D8. These supply independent transient conduction cases when reconstructing equivalent boundary conditions and material properties. |
| [Ansys layered PCB CAD pair](https://github.com/ansys/example-data/tree/380b0e7a8a89f96fe248358559854b1a4e971968/pyprimemesh/multi_layer_quad_mesh_pcb) and [`blockswithparameters.dsco`](https://github.com/ansys/pyansys-geometry/blob/d947036c49d69dedf6f8aa7a86d654d797fa046a/tests/integration/files/blockswithparameters.dsco) | Downloaded `multi_layer_quad_mesh_pcb.scdoc`, `multi_layer_quad_mesh_pcb.dsco` and the parameterized Discovery model. These can seed equivalent SpaceClaim and Discovery importer cases for layered interfaces and dimension-driven remeshing. The sources supply CAD geometry. TD importer links, thermal tags and synchronization results need to be authored and captured. |
| [pyNastran `models/msc/single_element-3d/static.bdf`](https://github.com/SteveDoyle2/pyNastran/blob/a310a8a7c7c8525b8f7045f4b98d93e04a0bf2be/models/msc/single_element-3d/static.bdf) | Downloaded and checked the single 20-node `CHEXA`. Use as an input for testing whether the TD Nastran import path retains high-order connectivity. Confirm the active DWG class and node order after import. |
| [meshio++ `quadratic.pat`](https://github.com/loumalouomega/meshioplusplus/blob/4f5e80dd6241cfe3a02e847cc173ee164eae7c81/tests/python/meshes/patran/quadratic.pat) | Downloaded and verified 75 point records and one element each with 10 (tetrahedron), 13 (pyramid), 15 (wedge) and 20 (brick) nodes, plus 6-node triangle and 8-node quad controls and a 3-node line. Each listed connectivity ID resolves to a point. Use the coordinates and topology to author individual OpenTD cases, mapping each format's corner and midside order explicitly. |
| [Gmsh `vtk_pyramids_order2.vtu`](https://github.com/live-clones/gmsh/blob/02d93b3425f21473b4114b5c26b74229465fad67/benchmarks/io_vtk/vtk_pyramids_order2.vtu) | Downloaded and decoded 153 points, 48 cells of VTK type 27 and 13 connectivity entries per cell. Use as a second pyramid connectivity and shared-node reference. |
| [Ansys lunar lander comparison files](https://github.com/ansys/example-data/tree/380b0e7a8a89f96fe248358559854b1a4e971968/pyfluent/lunar_lander_thermal) | Downloaded and verified `lander_geom.scdoc`, the Git LFS object `lander_mesh.msh.h5` and `apollo17_temp_data.csv`. The mesh is HDF5 and matches its LFS SHA-256. The Fluent example adapts a published Thermal Desktop study. Use the files for independent radiation, shell conduction and transient temperature comparisons. The source paper provides the TD model description and numerical comparisons. Its online record does not supply the native model. [Ansys example](https://examples.fluent.docs.pyansys.com/version/dev/examples/00-released_examples/06-lunar_lander_thermal.html), [Original study](https://doi.org/10.1155/2018/4236396) |

| Download | Bytes | Verified Git blob | SHA-256 |
| --- | ---: | --- | --- |
| `quadratic.pat` | 13,236 | `cf5a138b83dae2a67da66c7e8b32d3b998889ac7` | `f6322ffb2e42b6390aa12f6969ef0fd0469e1daf55fd9cd9d0c1fc74f9ee1cb0` |
| `vtk_pyramids_order2.vtu` | 13,292 | `d7c221537986acd0e9912c7281f4fca9cefbcf70` | `74dd557d2f07f3cc9b6d2a2a3639f58f1c82e62c7f5634c3613fee95371fbb6f` |

The [2026 R1 Thermal Desktop User's Manual, §18.2.3.5](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Thermal_Desktop_Users_Manual.pdf#page=929)
lists high-order `CTETRA`, `CPENTA` and `CHEXA` support for the TD Nastran
import path. Its supported-card list omits `CPYRAM`. Use the documented
`CreateQuadraticPyramid` method to author that DWG case and keep the Nastran
conversion as a separate compatibility check. Test the active DWG class and
ordered node handles after save and reopen for each solid type.
[OpenTD 2026 R1 class reference](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net8-reference/OpenTD.ThermalDesktop.md)

## Ansys 2026 R1 CAD synchronization and regeneration tutorials

Downloaded and inspected the public PDF editions. Both tutorial PDFs list
model archives by name. Their link annotations and embedded-file tables
yielded no archive download URL or attached model bytes. The Ansys Help
index's public tutorial HTML URLs returned 404 and the corresponding
authenticated routes returned 401 without sign-in. Checks of the documented
filenames on the public Ansys Help attachment and Ansys storage routes did not
return an archive. The table identifies the release-matched files to retrieve
through the tutorial portal or sample distribution.
[Ansys 2026 R1 documentation index](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/ai_sinfo/td_intro.html)

| Public PDF | Bytes | SHA-256 |
| --- | ---: | --- |
| [TD Designer Tutorials](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf) | 27,863,581 | `60304258ed5a47f3f9b18ad6efb83b7ae77a6a9b657725904d0568d3740d7d85` |
| [TD Designer User Manual](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_User_Manual.pdf) | 5,251,738 | `14fe70f1b86725d8f33b59b89ae6f2a788d52700a46526c115a6df855cc1d533` |
| [Thermal Desktop Tutorials](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Thermal_Desktop_Tutorials.pdf) | 28,569,421 | `a31a306579a89317fd5772a6a1b07440814673aaa3a4f93241178e712d645027` |

| Archive or procedure | Files and reference states to acquire |
| --- | --- |
| TD Designer `FinDiode.zip`, §§2.1–2.5 | `Heatsink_2.1.dwg`, `HeatSink_2.1.dsco`, `Diode.dsco` and the accompanying properties. Capture the starter DWG before linking, the first `Generate Finite Element Mesh` sync and the second sync after changing mesh controls. Capture domain tags and matched interfaces after adding the diode. Section 2.5 drives the `Fin_height` CAD parameter from the DWG symbol `FinHeight`. Save the dimension-driven update and an unchanged-dimension `Reuse Mesh` control with their DSCOs. [Initial sync and remesh](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf#page=75), [Driving Dimensions](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf#page=107) |
| TD Designer `SplitMesh.zip` and `SweptMesh.zip`, §§3.1 and 4.1 | `HeatSink_micro_split.dsco` and `HeatSink_micro_swept.dsco`, respectively. Generate and save linked DWGs with the shared interface split tag and the swept source/target selections. The guide names the DSCO starters. Whether the archives supply any matching DWGs is unverified. [Split Mesh](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf#page=113), [Swept Mesh](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf#page=121) |
| Thermal Desktop `compartments.zip`, §2.1 | `Compartment_Tutorial.dwg` from the archive and `Comp_Tank.scdoc` authored earlier in the TD Direct tutorial. Save the drawing and SCDOC around the FE-only synchronization. The procedure uses Curved Control Volume and a matched-mesh interface. The `Compartment.dwg` in the OpenTD demos has separate provenance. [Basic Compartments with TD Direct](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Thermal_Desktop_Tutorials.pdf#page=115) |
| Thermal Desktop `FEMWalledPipe.zip`, §2.7 | `pipeDuctWall.dwg` starts with a previously generated pipe-wall FE model. Retrieve its companions and screen the active element classes. The manual supplies neither a writer-build identifier for the starter nor its FE payload layout. [FEM Walled Pipe](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Thermal_Desktop_Tutorials.pdf#page=258) |

For Discovery coverage, record the `TDDHOST` selection, the linked document,
the importer class and the selected import modes. Capture CAD-only and FE-only
states as well as the synchronized mesh. Record geometry and face IDs, driving
dimensions, mesh settings, domain tags, and ordered nodes and elements for
each state. The user manual treats Curved Control Volume and Quadratic
Control Volume as distinct mesh methods. Capture and inspect both when
looking for explicit midside-node records.
[TD Designer User Manual, §§2.2 and 4.3.1.3](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_User_Manual.pdf)

## Vendor and training files to acquire

| Source | Files to request or retrieve through authorized access |
| --- | --- |
| CRTech TD Direct User Guide §5.1 | In the installed `Tutorials/TD Direct/Fin_Diode/` example, acquire `HeatSink_1.dwg` and `HeatSink_1.scdoc`, `2_Domains/HeatSink_2.dwg` and `HeatSink_2.scdoc`, `3_Mesh_Interfaces/HeatSink_3.dwg` and `HeatSink_3.scdoc` with `Diode.scdoc`, and `4_Local_Mesh/HeatSink_4.dwg` and `HeatSink_4.scdoc` with `Diode.scdoc`. Retain the corresponding companion files and completed checkpoints. These exercise initial link, domain tags, matched interfaces, local refinement and synchronization. Public documentation identifies these names. The native tutorial files were unavailable in the public downloads checked. [TD Direct User Guide](https://www.crtech.com/sites/default/files/files/Guides-Manuals/Protected/TDDirectUsersGuide.pdf) |
| CRTech TD Direct User Guide §5.2 | Request `Tutorials/TD Direct/Swept/ReactionWheel_1.dwg`, `ReactionWheel_1.scdoc`, the optical and thermophysical property files from the same directory, and the completed swept-mesh state. The starter DWG is prepared for an initial link to the SCDOC. Use the paired states for swept-mesh generation, material orienters and mesh-editor actions. The guide identifies the filenames. Native bytes and the generated class IDs remain unverified. [TD Direct User Guide](https://www.crtech.com/sites/default/files/files/Guides-Manuals/Protected/TDDirectUsersGuide.pdf), [CRTech training slides](https://www.crtech.com/sites/default/files/files/Training_Tutorials/TD%20Direct/TDDirect_V61.pdf) |
| CRTech OpenTD Project Hub | The official hub links `CRTest`, a utility for running drawings and comparing results. Ask for any distributable sample scripts with their DWGs, expected results and producing release. Public access to the linked attachment was unverified. [CRTech hub](https://www.crtech.com/news-items/opentd-project-hub), [CRTest topic](https://www.crtech.com/forum/topic/crtest-write-scripts-run-models-and-compare-results), [CRTech workshop description](https://tfaws.nasa.gov/wp-content/uploads/TFAWS2022-OpenTD-Tour.pdf) |
| CRTech samples and tutorials | Request a curved high-order mesh with its original DWG and CAD companion, and paired generated states. The published complex-cross-section heatpipe example is a candidate for shell-to-FE coupling. Its attachments and class counts remain unverified. [Sample Models and Applications forum](https://www.crtech.com/forum/1775), [CRTech access information](https://www.crtech.com/getting-started), [Heatpipe example](https://www.crtech.com/news-items/heatpipes-complex-cross-sections) |
| CRTech thermoelectric examples | The application page describes a curved single-stage FE module and a matched two-stage TD Direct example. The sample link points to forum topic 1675 and returned HTTP 403 on the production site. The attached filenames, element order and relationship to both illustrated examples remain unverified. [Thermoelectrics application](https://stagingsite.crtech.com/applications/thermoelectrics), [sample topic](https://www.crtech.com/forum/viewtopic.php?t=1675) |
| Ansys release-matched tutorial distributions | Use the [2026 R1 archive and member list above](#ansys-2026-r1-cad-synchronization-and-regeneration-tutorials) and request the corresponding 2025 R2 TD Direct starters and checkpoints. Record the importer family when collecting each release. [2025 R2 documentation](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/ai_sinfo/td_intro.html), [2026 R1 release notes](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Ansys_Release_Notes.pdf) |
| NASA legacy model archive | Appendix H of revision 5.1 lists Automated Aerobraking (2010, TD 5.3) as an open example model and identifies older open cases for Mars Odyssey, Mars Global Surveyor and Mars Reconnaissance Orbiter. The latter projects pair TD orbital or radiation models with Patran thermal models. Ask for the original, releasable TD 5.3 example drawing first and screen it for active legacy classes. The public guidebook and the three linked NTRS study records list PDF downloads only. The native archive filenames and DWG classes remain unverified. [NASA guidebook, pp. 192–193](https://ntrs.nasa.gov/api/citations/20220006584/downloads/NASAPassiveThermalGuidebookv5%201Public.pdf#page=192), [Mars Odyssey record](https://ntrs.nasa.gov/citations/20030065626), [Mars Global Surveyor record](https://ntrs.nasa.gov/citations/20030066233), [Mars Reconnaissance Orbiter record](https://ntrs.nasa.gov/citations/20070030304) |
| ESA standalone Thermal Desktop converters and test cases | ESA lists `td_tas_converters_beta_2019-08-09.zip` and `td_tas_converters_beta_2020-09-15.zip` and describes a separate test suite that includes real models. The later archive's download page requests contact details. Ask for releasable original test DWGs, exact writer builds and any paired exchange data. The public listing leaves archive membership and the target classes unverified. [ESA release and download list](https://exchange.esa.int/restricted/tasverter-2022/), [TASverter Thermal Desktop format notes](https://exchange.esa.int/download/tasverter/TASverter-r2022-12-20/doc/thermal_desktop.html) |
| Historical Thermal Desktop FE and native mesher examples | The vendor's early FE white paper and the 2008 TD 5.2 guide give leads for a pre-upgrade FE example and a native TDMesh controller. The guide describes CAD input, preview and generated FEM stages. Ask for the matching original DWGs and CAD files. Public searches for exact legacy class names and `TdMesherVa` yielded no confirmed active instances. The historical workflow name gives no on-disk class ID. [Vendor FEM white paper](https://stagingsite.crtech.com/finite-element-method-and-thermal-desktop), [Thermal Desktop 5.2 Advanced Modeling Techniques, §6](https://manualzilla.com/doc/5951221/thermal-desktop-advanced-modeling-techniques) |

The [TD Direct training slides](https://www.crtech.com/sites/default/files/files/Training_Tutorials/TD%20Direct/TDDirect_V61.pdf)
describe curved geometry with the same thermal node count as straight elements.
Capture both the stored connectivity and source curvature when comparing the
curved-mesh setting with explicit quadratic FE objects. NASA's
[`FilePlottingTools_v3.1_Release.zip`](https://github.com/nasa/FilePlottingTools/blob/4e480e1421e56219a9f2d9438f8fbbf77cfdf077/FilePlottingTools_v3.1_Release.zip)
provides SAV-reader source. Inspection of the archive and its embedded earlier
release yielded no SAV or DWG members.

## Results from the independent decoder

Across 25 AC1032 drawing snapshots, the expanded codecs decoded and built
boundaries for 7,788 additional tetrahedra, 1,156 wedges and four bricks using
element-node v6 and solid-attribute v14. Each resolved the ordered nodes in its
own drawing. The new reader consumed v6 expressions for 8,186 node records.
It also decoded 62 FD bricks, 12 curved FD solids and 36 marker-55 rectangles.
Of these, 62 FD bricks, 11 curved solids and 14 rectangles passed static
boundary export. The other 23 hit the static size guard.

The AC1027 and AC1032 checks establish local structural and geometric coverage.
Geometry-derived heat capacity, conductivity, contact, radiation and solver
comparisons still need mapped inputs and independent reference results. Public
automation uses owned synthetic records. Acquired drawings, coordinates and
raw inspection results remain local.

### Geometry and stored-mesh follow-up

The marker-56 reader consumed the data, text and handle streams for 6,213
records in the 25-drawing snapshot set. Static export passed for all 5,943
triangles, 20 quads, 209 rectangles, 24 FD meshes, 3 cones, 4 cylinders, 8 disks
and 2 spheres in that revision. Nine surfaces used a decimal-rounded full
revolution and closed correctly after angle normalization.

| Source | Stored geometry verified locally |
| --- | --- |
| CMU TD Direct test | Selecting the SpaceClaim or FE importer exports 52 triangles and 54 tetrahedra. The declared SpaceClaim companion resolves in the captured tree. |
| UC Davis Mapping Results | Selecting the FE importer exports 103 quads. All 127 DWG node IDs and coordinates match `coarse_quad.NAS` exactly. All 103 element connectivities match after allowing cyclic rotation and winding reversal. |
| OpenTD demo meshers | The two `TdMesher` objects export 1,645 and 7,705 linked elements. The larger export has 27,376 faces. |
| Installed Heating Coil examples | The mesh-bearing SpaceClaim importer and FE importer each select 12,900 elements per drawing. The second SpaceClaim importer has CAD links only. |

The checks preserve original bytes and use stored nodes and elements.
Mesh settings, live CAD synchronization and solver qualification remain open.
Raw model, CAD, mesh and result files remain local.

### Legacy and quadratic readers and saved mesh comparison

Static review of the installed 6.3 reader identified the wrapped legacy
linear and quadratic solid paths and the exact registered spelling
`TdMesherVA`. Owned records exercise the supported revision branches and
ordered node references. The downloaded PAT fixture also passed the boundary
export for all four quadratic solids, generating 16 tet faces, 20 pyramid
faces, 20 wedge faces and 24 brick faces. The PAT check provides independent
geometry input. Native DWG layout confirmation awaits original examples.

The saved-state comparison reported the public CMU TD Direct mesh unchanged
when compared with itself. It resolved 29 nodes, 106 elements and three saved
DWG mesh groups with matching memberships. The owned
Discovery companion scenario exercises a first mesh, a saved reuse control
and missing-companion handling. The local runtime probe found no licensed
AutoCAD host, so no vendor sync or mesh generation was run. See the
[command and scope](../docs/td-sinda.md#geometry-and-remaining-format-evidence).

### Original drawings for polygon and layout validation

The public downloads inspected in this search yielded zero drawings with
the required active classes. A class-table name alone cannot establish
that a drawing contains a matching object. Confirm the C++ and DXF class
pair and a nonzero instance count on the untouched drawing or DWG-format
backup before opening or resaving it in Thermal Desktop.

| Target | Source and exact artifact to acquire | Public evidence checked |
| --- | --- | --- |
| Legacy FE | Request the original TD 5.3 **Automated Aerobraking** example DWG described in Appendix H and the exact build and companion files. For a second independent case, request the original TD mirror-assembly drawing and matching Nastran bulk data from the 2001 NGST finite-element study. The 2003 C&R class solids exercises are a lead for tetrahedron, wedge and brick drawings. | The aerobraking assessment identifies the converted all-TD model in Appendix D. The linked conference paper and the mirror-assembly paper had no embedded files or model links. The mirror paper documents a Nastran import with node and element correspondence. Actual element classes and original filenames remain unverified. [Aerobraking study](https://ntrs.nasa.gov/citations/20100030599), [NASA assessment, Appendix D](https://ntrs.nasa.gov/api/citations/20120001988/downloads/20120001988.pdf), [NGST mirror study](https://ntrs.nasa.gov/citations/20020050386), [C&R class slides 42–44](https://tfaws.nasa.gov/TFAWS03/software_training/thermal_desktop.pdf#page=42) |
| Quadratic solids | Request the Thermal Desktop DWG and source CAD from the Ansys 2025 R2 **Quadratic thermal elements** release demonstration. Ask for four small saved DWGs, or a single mixed drawing containing the 10-, 13-, 15- and 20-node solids, with the corresponding OpenTD node and element exports. Use the pinned PAT and VTU files above as geometry inputs for a vendor-written reference if individual solids are missing. | The release article illustrates the feature and gives the customer download route. It supplies no native model link. In the 2027 R1 demo archive, `FEMeshExample/FEMeshExample.cs` and `FeMeshSpiral/FeMeshSpiralDialog.cs` build meshes in-session. The archive yielded no native quadratic-solid examples. [Ansys 2025 R2 release demonstration](https://ansys.synopsys.com/blog/whats-new-ansys-fluids-2025-r2), [OpenTD creation methods](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net8-reference/OpenTD.ThermalDesktop.md) |
| `TdMesherVA` and Discovery importer | Request a saved TD example with a confirmed `TdMesherVA` instance (DXF name `TDMESHERVA`), CAD input and generated mesh. For Discovery, prioritize the `FinDiode.zip` pair above and a DWG saved after first synchronization with its matching `.dsco`. | The public 2008 TDMesh guide establishes the preview and generated workflow. The 2026 R1 tutorial PDFs name the Discovery files. The checked public routes yielded no matching original model pair. [TDMesh guide, §6](https://manualzilla.com/doc/5951221/thermal-desktop-advanced-modeling-techniques), [TD Designer Fin Diode tutorial](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_Tutorials.pdf#page=71) |

### Historical polygon sources

The historical `RcPolygon` C++ class is optional for WP-08. An original
saved DWG or BAK from the 2003 C&R Polygon exercise would support a
separate compatibility extension. Preserve the original drawing and its
companion property files if acquired.

The oldest source located that explicitly describes the Thermal Desktop
**Polygon** surface is the 2002 Swales paper. The earliest verified
documentation for single-face `MeshFD` polygons is the installed
`OpenTD 61 Class Reference.chm`, SHA-256
`3cf7bb96c7c4bade06e7aa5a2e84f2a4303f02175bfa35f3e0ba2268b0101c5a`.
Its `OpenTDv61.ThermalDesktop.CreatePolygon` and
`OpenTDv61.RadCAD.Polygon` topics identify the single-face representation.
C&R announced 6.1 on April 24, 2019. The exact first release of that
representation and any earlier native `RcPolygon` class remain unverified.
[C&R release archive](https://www.crtech.com/news/news-archive/all/201904)

| Date and source | Evidence and acquisition lead |
| --- | --- |
| 2000 NASA/JPL STEP-TAS pilot | The proceedings identify the TD 3.3 beta and report that C&R implemented triangle and quadrilateral exchange. Look for the original TD pilot and primitive-test drawings and their STEP-TAS counterparts. The report describes exchange shapes and provides an excerpt of a STEP file. The native classes and DWG filenames are unverified. [Pilot proceedings, printed p. 219](https://tfaws.nasa.gov/TFAWS00/CP-2002-211486.pdf#page=225) |
| 2002 Swales TSS geometry conversion | Table 2 identifies a point-defined Thermal Desktop Polygon and says triangles and quads can be represented by the polygon entity type. The companion ESA presentation repeats the comparison. The public proceedings provide the paper and slides. Seek a period TD drawing with the corresponding TSS geometry if a polygon conversion case survives. [TFAWS paper, table 2](https://tfaws.nasa.gov/TFAWS02/Data/Thermal/Peabody.pdf#page=4), [ESA slides, Geometric Shapes](https://exchange.esa.int/download/thermal-workshop/workshop2002/viewgraphs/swales/peabody/tss-neutral.pdf#page=5) |
| 2003 C&R Thermal Desktop/RadCAD hands-on course | Strongest early polygon lead. The handout lists **Polygon** and **From AutoCAD Surface** separately. Request the pre-upgrade Polygon exercise with its property files, plus the separate worked mesh conversion drawing if available. The public archive links the class PDF and supplies no native class data. [Course listing](https://tfaws.nasa.gov/TFAWS03/software_courses.html), [class materials](https://tfaws.nasa.gov/TFAWS03/tfaws03_events.html), [slides 36–37](https://tfaws.nasa.gov/TFAWS03/software_training/thermal_desktop.pdf#page=36) |
| 2005 C&R hands-on course and non-grey radiation examples | The course outline identifies the finite-difference and RadCAD sessions. The separate non-grey slides name `thermal48.dwg` and `ShieldsSimple.dwg` and show TD 4.8 Beta 4. The slides describe rectangles and spherical shields, so these filenames are leads for the period exercise archive and comparison drawings. Request any explicit Polygon exercise from the hands-on pack. No model download was located on the checked course pages. [Course outline](https://tfaws.nasa.gov/TFAWS05/Website/cr_t_t_d.htm), [non-grey short course](https://tfaws.nasa.gov/TFAWS05/Website/files/Non-Grey%20Radiation%20Short%20Course.pdf) |
| 2006 CRaTER reduced thermal model archive | Table 1 names `CRaTER_B00H_051506`, `CRaTER_B90C_SS_051506` and `CRaTER_B90C_SUR_051506` as native TD model basenames. A screenshot shows TD 4.7 Patch 44. The report also specifies the TSS geometry export `CRaTER_NA_EXT_051706.tssgm` and lists companion optics and materials. These are leads for a paired native and neutral-format case. The model bytes and polygon contents were unverified. [CRaTER model report, table 1 and §3.3](https://snebulos.mit.edu/projects/crater/file_cabinet/0/04017/04017_02_r02.pdf) |
| 2007 C&R/ESA STEP-TAS test suite | The TD 5.1 presentation names the ESA primitive test suite and demonstrates `rcWriteTAS` and `rcReadTAS`. Request the original native test drawings and corresponding STEP-TAS inputs, especially triangles or quads. The presentation gives no native download or polygon class names. ESA's later converter packages postdate the 6.1 bound and use OpenTD. [2007 workshop slides](https://tfaws.nasa.gov/TFAWS07/Proceedings/TFAWS07-1011.pdf#page=15), [ESA converter release information](https://exchange.esa.int/restricted/tasverter/) |
| 2012 and 2018 NASA GSFC conversion references | The 2012 short course lists Polygon among the surfaces stored in a TD DWG. The 2018 paper describes the TSS triangle-fan representation and how a four-sided case can be nonplanar. Request a small original TD DWG and its matching TSS export from that workflow, with the writer build. The public conversion report lists only its PDF. [2012 short course](https://ntrs.nasa.gov/api/citations/20120013640/downloads/20120013640.pdf), [2018 converter paper](https://ntrs.nasa.gov/citations/20180004561) |

The C&R [Tutorials](https://www.crtech.com/forum/1764) and
[Sample Models and Applications](https://www.crtech.com/forum/1775) forums
require sign-in. The [product download guidance](https://www.crtech.com/news-items/product-updates)
also requires sign-in. An authorized TD 3.x–5.x installer, manual or
exercise pack would let us check version-matched class registration and
an original polygon example. The Wayback and Common Crawl index queries
were unavailable during this search. No public native polygon drawing
from before 6.1 was recovered.

The installed `beercan.bak` was checked as an additional local control.
It is a 65,809-byte AC1027 DWG with one disk, eight linear triangles,
40 linear quads, 32 linear wedges and 32 linear bricks. Its class table
and active records contain zero `RcPolygon` or `RcMeshFD` instances.
SHA-256
`6ba8037a6c7a1870ca8be1ead4f0ecfd782ca0d7000addde35a353ec02df0d79`.
The DWG container version leaves the Thermal Desktop writer build open.

For an acquired DWG, record the C++ class, DXF name, active instance count
and original hash before upgrading. FCST accepts `RCPOLYGON` as a DXF
name for C++ class `RcMeshFD`, so a DXF name alone cannot establish an
`RcPolygon` instance. Keep any TSS export for comparison of ordered
vertices, nodalization and optical assignments. For the modern control,
the current `CreatePolygon` API yields a single-face `MeshFD`. The 2027 R1
archive's `Comprehensive/Comprehensive.cs` calls it and saves a drawing at
runtime. The saved output is absent from the archive.
[FCST class mapping](../python/fcst_exchange/td_decode.py),
[OpenTD polygon documentation](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net8-reference/OpenTD.ThermalDesktop.md)

### Original drawing checks for the 6.3 profile

A deduplicated rescreen of 30 AC1032 drawings with retained native inventories
found four active `TdScImporter` records. It found zero instances of the
target legacy FE wrappers, quadratic solids, `TdMesherVA`, ogive, scarfed
surfaces or solid ellipsoid. The user conditionally accepted DWG layout
validation on the available structural and analytic evidence. Comparisons
against original target instances remain deferred until drawings are available.
The CMU SpaceClaim pair passed the unchanged saved-mesh check with
29 nodes, 106 elements and three matching mesh groups. This is a
same-drawing control. The historical UC Davis CubeSat drawing contains a
v12 case manager advertising four cases. The reader recovered the first
v78 case header and preserved the remaining fields as opaque.

## Files still needed for full coverage

The names below are proposed for new test fixtures. The inspected drawings
supply mesher and importer records and linear-element examples. The conic,
element-order, legacy FE and `TdMesherVA` layout comparisons are deferred
under the conditional acceptance. The linked CAD states and geometry physics
files still support open acceptance work.

| Proposed fixture | Required contents |
| --- | --- |
| `td-conics.dwg` | `RcOgive` with full and partial sweeps, `RcScarfedCone` and `RcScarfedCylinder` with nonzero scarf angles of both signs, and `RcFdSolidEllipsoid` with independently trimmed, nonproportional inner and outer walls. Include source boundary coordinates, areas and solid volume where applicable. |
| `td-fe-orders.dwg` | Quadratic triangle, quadrilateral, tetrahedron, pyramid, wedge and brick with displaced midside nodes, plus linear counterparts including pyramid. The PAT and VTU inputs above supply independent connectivity. Verify active `RcQuadraticTet`, `RcQuadraticPyramid`, `RcQuadraticWedge` and `RcQuadraticBrick` records and capture TD's ordered source nodes, edge and face connectivity and curved boundary coordinates. |
| `td-fe-legacy.dwg` | Original `RcLinearTri`, `RcLinearQuad`, `RcLinearTet`, `RcLinearWedge` and `RcLinearBrick` class instances. Preserve the pre-upgrade originals and record the writer build for both originals and any separately saved upgraded copies. |
| `td-mesher-before.dwg`, `td-mesher-generated.dwg` and source CAD companion | Start with the public `TdMesher` and TD Direct importer examples above. Acquire a drawing with an active `TdMesherVA` instance, its input geometry and any preview and generated states. Record the writer build, class ID and object links. |
| Linked CAD synchronization and regeneration states | Use the CMU pair and TD Direct tutorials for SpaceClaim, and the Fin Diode tutorial for Discovery. For each host, retain matching DWG and companion copies from before sync, after first mesh, and after one controlled CAD or mesh-control change. Include an unchanged sync or reuse control and capture the geometry, tags and connectivity needed to check regeneration. |
| `td-geometry-physics.dwg` with case files | Use the FE conduction/radiation, contact and result samples above as starting points. Acquire property databases, actual generated SINDA deck and all includes, case settings, node/face IDs, areas and volumes, and saved results or a bounded export. Cover geometry-derived conductance and capacity, layering and orientation, optical properties, radiation groups, contactors, and surface or volume loads. |

For required profile validation, acquire or generate matching cases in
TD 6.3.022. Record the exact writer build and original file hash, and
retain the generated decks and results with the version that produced them.
Additional serialization revisions, including 2025 R2 and 2026 R1, are
optional. The [2025 R2 OpenTD API](https://developer.synopsys.com/docs/opentd-net8-reference-2025-r2/class_open_t_d_1_1_thermal_desktop.xhtml)
and [2026 R1 OpenTD API](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net8-reference/OpenTD.ThermalDesktop.md)
document geometry creation, including ogive, scarfed surfaces and quadratic
elements. They provide a way to generate fresh reference cases on a licensed
installation. The [SolidEllipsoid class reference](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net4-reference/OpenTD.RadCAD.FdSolid.SolidEllipsoid.md)
documents separate inner and outer X/Y/Z radii and min/max height fields.
For legacy fixtures, record active DWG class IDs before upgrading. For
TD Designer synchronization, preserve the `.dsco` companion and capture
the linked drawing on both sides of the edit. [TD Designer user manual](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/TD_Designer_User_Manual.pdf)

Downloaded samples and raw read outputs are retained in ignored
`.local/wp08-online-geometry-sources/`. Keep original third-party and
restricted files local and review rights, metadata and exact outgoing evidence
under TST-021 before redistribution.
