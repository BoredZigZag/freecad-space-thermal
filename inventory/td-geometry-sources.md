# WP-08 Thermal Desktop geometry and physics sources

Checked online and through public repository history on 2026-11-13 against the [geometry support matrix](../docs/td-sinda.md) and
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

The seven public commits affecting the [OpenTD downloads directory](https://github.com/ansys/DevRelPublic/commits/main/Downloads/Thermal-Desktop-OpenTD)
add no distinct demo archive beyond the four above. The older
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
| [Ansys lunar lander comparison files](https://github.com/ansys/example-data/tree/380b0e7a8a89f96fe248358559854b1a4e971968/pyfluent/lunar_lander_thermal) | Downloaded and verified `lander_geom.scdoc`, the Git LFS object `lander_mesh.msh.h5` and `apollo17_temp_data.csv`. The mesh is HDF5 and matches its LFS SHA-256. The Fluent example adapts a published Thermal Desktop study. Use the files for independent radiation, shell conduction and transient temperature comparisons. The source paper provides the TD model description and numerical comparisons. Its online record does not supply the native model. [Ansys example](https://examples.fluent.docs.pyansys.com/version/dev/examples/00-released_examples/06-lunar_lander_thermal.html), [Original study](https://doi.org/10.1155/2018/4236396) |

## Vendor and training files to acquire

| Source | Files to request or retrieve through authorized access |
| --- | --- |
| CRTech TD Direct User Guide §5.1 | In the installed `Tutorials/TD Direct/Fin_Diode/` example, acquire `HeatSink_1.dwg` and `HeatSink_1.scdoc`, `2_Domains/HeatSink_2.dwg` and `HeatSink_2.scdoc`, `3_Mesh_Interfaces/HeatSink_3.dwg` and `HeatSink_3.scdoc` with `Diode.scdoc`, and `4_Local_Mesh/HeatSink_4.dwg` and `HeatSink_4.scdoc` with `Diode.scdoc`. Retain the corresponding companion files and completed checkpoints. These exercise initial link, domain tags, matched interfaces, local refinement and synchronization. Public documentation identifies these names. The native tutorial files were unavailable in the public downloads checked. [TD Direct User Guide](https://www.crtech.com/sites/default/files/files/Guides-Manuals/Protected/TDDirectUsersGuide.pdf) |
| CRTech TD Direct User Guide §5.2 | Request `Tutorials/TD Direct/Swept/ReactionWheel_1.dwg`, `ReactionWheel_1.scdoc`, the optical and thermophysical property files from the same directory, and the completed swept-mesh state. The starter DWG is prepared for an initial link to the SCDOC. Use the paired states for swept-mesh generation, material orienters and mesh-editor actions. The guide identifies the filenames. Native bytes and the generated class IDs remain unverified. [TD Direct User Guide](https://www.crtech.com/sites/default/files/files/Guides-Manuals/Protected/TDDirectUsersGuide.pdf), [CRTech training slides](https://www.crtech.com/sites/default/files/files/Training_Tutorials/TD%20Direct/TDDirect_V61.pdf) |
| CRTech OpenTD Project Hub | The official hub links `CRTest`, a utility for running drawings and comparing results. Ask for any distributable sample scripts with their DWGs, expected results and producing release. Public access to the linked attachment was unverified. [CRTech hub](https://www.crtech.com/news-items/opentd-project-hub), [CRTest topic](https://www.crtech.com/forum/topic/crtest-write-scripts-run-models-and-compare-results), [CRTech workshop description](https://tfaws.nasa.gov/wp-content/uploads/TFAWS2022-OpenTD-Tour.pdf) |
| CRTech samples and tutorials | Request a curved high-order mesh with its original DWG and CAD companion, and paired generated states. The published complex-cross-section heatpipe example is a candidate for shell-to-FE coupling. Its attachments and class counts remain unverified. [Sample Models and Applications forum](https://www.crtech.com/forum/1775), [CRTech access information](https://www.crtech.com/getting-started), [Heatpipe example](https://www.crtech.com/news-items/heatpipes-complex-cross-sections) |
| CRTech thermoelectric examples | The application page describes a curved single-stage FE module and a matched two-stage TD Direct example. The sample link points to forum topic 1675 and returned HTTP 403 on the production site. The attached filenames, element order and relationship to both illustrated examples remain unverified. [Thermoelectrics application](https://stagingsite.crtech.com/applications/thermoelectrics), [sample topic](https://www.crtech.com/forum/viewtopic.php?t=1675) |
| Ansys 2025 R2 and 2026 R1 tutorials | Retrieve the native files through the release-matched Thermal Desktop/TD Direct or TD Designer tutorial guide or installed examples. The public documentation index lists the guides. The checked public tutorial links did not deliver the model archives. The 2026 R1 release notes describe the transition to TD Designer, so record the importer family when collecting that release. [2025 R2 documentation](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/ai_sinfo/td_intro.html), [2026 R1 documentation](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/ai_sinfo/td_intro.html), [2026 R1 release notes](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/pdf/Ansys_Release_Notes.pdf) |
| NASA legacy model archive | Appendix H lists historical models and release conditions. It directs readers to the agency archive and model custodians. The guidebook provides provenance leads for an original pre-upgrade TD file. No candidate from that archive was acquired. [NASA Passive Thermal Control Engineering Guidebook, Appendix H](https://ntrs.nasa.gov/citations/20220006584) |

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

The checks preserve original bytes and use stored nodes and elements. They leave
mesh settings, CAD synchronization, generated-state comparison and solver
qualification open. Raw model, CAD, mesh and result files remain local.

## Files still needed for full coverage

The names below are proposed for new test fixtures. The inspected drawings
supply mesher and importer records and linear-element examples. The remaining
class and parameter combinations need purpose-built drawings or verified
vendor examples.

| Proposed fixture | Required contents |
| --- | --- |
| `td-conics.dwg` | `RcOgive` with full and partial sweeps, `RcScarfedCone` and `RcScarfedCylinder` with nonzero scarf angles of both signs, and `RcFdSolidEllipsoid` with independently trimmed, nonproportional inner and outer walls. Include source boundary coordinates, areas and solid volume where applicable. |
| `td-fe-orders.dwg` | Quadratic triangle, quadrilateral, tetrahedron, pyramid, wedge and brick with displaced midside nodes, plus linear counterparts including pyramid. Capture TD's ordered source nodes, edge and face connectivity and curved boundary coordinates. |
| `td-fe-legacy.dwg` | Original `RcLinearTri`, `RcLinearQuad`, `RcLinearTet`, `RcLinearWedge`, `RcLinearBrick` and `RcPolygon` class instances. Preserve the pre-upgrade originals and record the writer build for both originals and any separately saved upgraded copies. |
| `td-mesher-before.dwg`, `td-mesher-generated.dwg` and source CAD companion | Start with the public `TdMesher` and TD Direct importer examples above. Add a confirmed `TdMesherVa` case, and capture the same model before and after mesh generation and a controlled parameter change. Include CAD face identifiers, controls and tags, source node and element maps, and the companion document used by that importer. |
| `td-geometry-physics.dwg` with case files | Use the FE conduction/radiation, contact and result samples above as starting points. Acquire property databases, actual generated SINDA deck and all includes, case settings, node/face IDs, areas and volumes, and saved results or a bounded export. Cover geometry-derived conductance and capacity, layering and orientation, optical properties, radiation groups, contactors, and surface or volume loads. |

For release comparison, acquire or generate matching cases in TD 6.3.022,
2025 R2 and 2026 R1. Record the exact writer build and original file hash,
and retain the generated decks and results with the version that produced
them. The [2025 R2 OpenTD API](https://developer.synopsys.com/docs/opentd-net8-reference-2025-r2/class_open_t_d_1_1_thermal_desktop.xhtml)
and [2026 R1 OpenTD API](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net8-reference/OpenTD.ThermalDesktop.md)
document geometry creation, including ogive, scarfed surfaces and quadratic
elements. They provide a way to generate fresh reference cases on a licensed
installation. The [SolidEllipsoid class reference](https://developer.synopsys.com/docs/opentd-reference-2026-r1/net4-reference/OpenTD.RadCAD.FdSolid.SolidEllipsoid.md)
documents separate inner and outer X/Y/Z radii and min/max height fields.
For legacy fixtures, record active DWG class IDs before upgrading. For
TD Designer synchronization, preserve the `.dsco` companion and capture
the linked drawing on both sides of the edit. [TD Designer user manual](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/pdf/TD_Designer_User_Manual.pdf)

Downloaded samples and raw read outputs are retained in ignored
`.local/wp08-online-geometry-sources/`. Keep original third-party and
restricted files local and review rights, metadata and exact outgoing evidence
under TST-021 before redistribution.
