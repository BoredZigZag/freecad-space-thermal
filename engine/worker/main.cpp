// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/build_info.hpp"
#include "fcst/diagnostic.hpp"
#include "fcst/contracts.hpp"
#include "fcst/thermal.hpp"
#include "fcst/thermal_steady.hpp"
#include "fcst/thermal_transient.hpp"
#include "fcst/radiation.hpp"
#include "fcst/environment.hpp"
#include "fcst/spatial.hpp"
#include "offline_probe.hpp"
#include <iostream>
#include <string>
#include <string_view>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
int main(int argc, char* argv[]) {
  if (argc==4 && std::string_view(argv[1])=="--offline-probe") return offline_probe(argv[2],argv[3]);
  if (argc == 4 && std::string_view(argv[1]) == "--worker") {
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
#endif
    return fcst::run_worker(argv[2], argv[3]);
  }
  const std::string_view operation=argc>=2?argv[1]:"";
  if ((argc == 3 && operation == "--contract") ||
      (argc == 2 && (operation == "--environment-transient" || operation == "--spatial-evaluate" ||
       operation == "--radiation-evaluate" || operation == "--radiation-steady" || operation == "--radiation-beam" ||
       operation == "--thermal-prepare" || operation == "--thermal-steady" || operation == "--thermal-transient"))) {
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1) return 2;
#endif
    std::string input;
    char c;
    while (input.size() <= 1048576 && std::cin.get(c)) input += c;
    auto result = argc == 2 ? (operation == "--spatial-evaluate" ? fcst::spatial::inspect(input) :
      operation == "--radiation-evaluate" || operation == "--radiation-steady" ? fcst::radiation::inspect(input,operation == "--radiation-steady") :
      operation == "--radiation-beam" ? fcst::radiation::inspect_beam(input) :
      operation == "--environment-transient" ? fcst::environment::inspect(input) :
      operation == "--thermal-transient" ? fcst::thermal::inspect_transient(input) :
      operation == "--thermal-steady" ? fcst::thermal::inspect_steady(input) : fcst::thermal::inspect(input)) : fcst::inspect_contract(argv[2], input);
    std::cout << result << '\n';
    return result.find("\"status\":\"passed\"") != std::string::npos ? 0 : 1;
  }
  if (argc == 2 && std::string_view(argv[1]) == "--build-info") {
    std::cout << "{\"engine\":\"fcst_native\",\"version\":\"" << FCST_VERSION
              << "\",\"compiler\":\"" << FCST_COMPILER
              << "\",\"compiler_version\":\"" << FCST_COMPILER_VERSION
              << "\",\"source_revision\":\"" << FCST_SOURCE_REVISION
              << "\",\"cxx_standard\":20,\"solver_available\":false,\"steady_available\":true,\"transient_available\":true,\"protocol_version\":1}\n";
    return 0;
  }
  if (argc==2 && std::string_view(argv[1])=="--thermal-capabilities") {
    std::cout<<fcst::thermal::inspect_thermal_capabilities()<<'\n';return 0;
  }
  if (argc == 2 && std::string_view(argv[1]) == "--self-test") {
    return fcst::code_name(fcst::DiagnosticCode::invalid_argument) == "invalid_argument" ? 0 : 1;
  }
  // Never echo untrusted arguments or claim an unimplemented solve succeeded.
  std::cerr << "{\"code\":\"not_implemented\",\"message\":\"Requested solve operation is not implemented\"}\n";
  return 2;
}
