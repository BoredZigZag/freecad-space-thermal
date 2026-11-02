// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
#include "fcst/thermal.hpp"
#include <span>

namespace fcst::spatial {
using Vector = std::array<double,3>;
struct Point { std::string id; std::size_t node; Vector position; };
struct Cell {
  std::string id, topology;
  std::size_t material;
  std::vector<std::size_t> points;
  double thickness = 0;
};
struct Surface {
  std::string id, kind;
  std::vector<std::size_t> points;
  double value, ambient;
};
struct Contact {
  std::string id, kind, provenance;
  std::vector<std::pair<std::size_t,double>> from, to;
  double area, coefficient, gap, minimum_temperature, maximum_temperature, maximum_power;
};
struct Quadrature { double volume; std::vector<double> shape; std::vector<Vector> gradient; Vector normal; };
struct PreparedCell { Cell cell; std::vector<Quadrature> quadrature; };
struct Discretization {
  std::string mesh_revision;
  std::vector<Point> points;
  std::vector<PreparedCell> cells;
  std::vector<Surface> surfaces;
  std::vector<Contact> contacts;
};
struct Contribution { std::size_t row,column; double value; };
struct Evaluation {
  std::vector<double> conductive,load,environment;
  std::vector<Contribution> jacobian;
  std::vector<Vector> cell_flux;
};
// Geometry is SI/global. Supported first-order families use full quadrature and row-sum storage.
PreparedCell prepare(Cell, std::span<const Point>);
void attach(thermal::Data&, Discretization);
Evaluation evaluate(const Discretization&, const thermal::Data&, std::span<const double>, bool);
bool nonlinear(const Discretization&, const thermal::Data&);
std::string inspect(std::string_view);
} // namespace fcst::spatial
