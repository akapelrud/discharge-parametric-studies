/* chombo-discharge
 * Copyright © 2025 SINTEF Energy Research.
 * Please refer to Copyright.txt and LICENSE in the chombo-discharge root directory.
 */

/*!
  @file   CD_ItoKMCBackgroundEvaluatorImplem.H
  @brief  Implementation of CD_ItoKMCBackgroundEvaluator.H
  @author Robert Marskar
*/

#ifndef CD_ItoKMCBackgroundEvaluatorImplem_H
#define CD_ItoKMCBackgroundEvaluatorImplem_H

// Our includes
#include <CD_ItoKMCBackgroundEvaluator.H>
#include <CD_NamespaceHeader.H>

using namespace Physics::ItoKMC;

template <typename I, typename C, typename R, typename F>
ItoKMCBackgroundEvaluator<I, C, R, F>::ItoKMCBackgroundEvaluator(RefCountedPtr<ItoKMCPhysics>& a_physics) noexcept
  : ItoKMCGodunovStepper<I, C, R, F>(a_physics)
{
  CH_TIME("ItoKMCBackgroundEvaluator::ItoKMCBackgroundEvaluator");

  ParmParse pp("ItoKMCBackgroundEvaluator");

  m_exitCrit = std::numeric_limits<Real>::max();

  pp.query("exit_crit", m_exitCrit);
}

template <typename I, typename C, typename R, typename F>
void
ItoKMCBackgroundEvaluator<I, C, R, F>::postInitialize() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::postInitialize");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::postInitialize" << endl;
  }

  ItoKMCGodunovStepper<I, C, R, F>::postInitialize();

  this->computeBackgroundField();
}

template <typename I, typename C, typename R, typename F>
void
ItoKMCBackgroundEvaluator<I, C, R, F>::postRegrid() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::postRegrid");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::postRegrid" << endl;
  }

  ItoKMCGodunovStepper<I, C, R, F>::postRegrid();

  this->computeBackgroundField();
}

template <typename I, typename C, typename R, typename F>
void
ItoKMCBackgroundEvaluator<I, C, R, F>::postCheckpointSetup() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::postCheckpointSetup");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::postCheckpointSetup" << endl;
  }

  ItoKMCGodunovStepper<I, C, R, F>::postCheckpointSetup();

  this->computeBackgroundField();
}

template <typename I, typename C, typename R, typename F>
void
ItoKMCBackgroundEvaluator<I, C, R, F>::printStepReport() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::printStepReport");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::printStepReport" << endl;
  }

  const Real k = this->evaluateSpaceChargeEffects();

  ItoKMCGodunovStepper<I, C, R, F>::printStepReport();
  const std::string whitespace = "                                   ";
  pout() << whitespace + "Delta E     = " << 100.0 * k << " (%)" << endl;

  if (k > m_exitCrit) {
    MayDay::Abort("ItoKMCBackgroundEvaluator -- abort because field changed by more than specified threshold");
  }
}

template <typename I, typename C, typename R, typename F>
void
ItoKMCBackgroundEvaluator<I, C, R, F>::computeBackgroundField() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::computeBackgroundField");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::computeBackgroundField" << endl;
  }

  // Allocate the background field, storage for the potential, storage for the space-charge, and storage for the
  // surface charge.
  MFAMRCellData phi;
  MFAMRCellData rho;
  EBAMRIVData   sigma;

  (this->m_amr)->allocate(phi, this->m_fluidRealm, 1);
  (this->m_amr)->allocate(rho, this->m_fluidRealm, 1);
  (this->m_amr)->allocate(sigma, this->m_fluidRealm, this->m_plasmaPhase, 1);
  (this->m_amr)->allocate(m_backgroundField, this->m_fluidRealm, SpaceDim);

  // Copy the potential over from the field solver so we have a better initial guess for the potential. The
  // space-charge and surface charge must be zero.
  (this->m_amr)->copyData(phi, (this->m_fieldSolver)->getPotential());

  DataOps::setValue(rho, 0.0);
  DataOps::setValue(sigma, 0.0);

  // Reset the field solver permittivities. Note that this discards the semi-implicit coefficients for the field update,
  // but these are refilled on the next solver time step anyways.
  (this->m_fieldSolver)->setPermittivities();

  const MFAMRCellData& permCell = (this->m_fieldSolver)->getPermittivityCell();
  const MFAMRFluxData& permFace = (this->m_fieldSolver)->getPermittivityFace();
  const MFAMRIVData&   permEB   = (this->m_fieldSolver)->getPermittivityEB();

  (this->m_fieldSolver)->setSolverPermittivities(permCell, permFace, permEB);

  // Solve the damn thing, and then compute the electric field onto m_backgroundField.
  (this->m_fieldSolver)->solve(phi, rho, sigma, false);
  (this->m_fieldSolver)->computeElectricField(m_backgroundField, phi);
}

template <typename I, typename C, typename R, typename F>
Real
ItoKMCBackgroundEvaluator<I, C, R, F>::evaluateSpaceChargeEffects() noexcept
{
  CH_TIME("ItoKMCBackgroundEvaluator::evaluateSpaceChargeEffects");
  if (this->m_verbosity > 5) {
    pout() << "ItoKMCBackgroundEvaluator::evaluateSpaceChargeEffects" << endl;
  }

  EBAMRCellData poissonNorm;
  EBAMRCellData laplaceNorm;
  EBAMRCellData deltaE;

  (this->m_amr)->allocate(poissonNorm, this->m_fluidRealm, this->m_plasmaPhase, 1);
  (this->m_amr)->allocate(laplaceNorm, this->m_fluidRealm, this->m_plasmaPhase, 1);
  (this->m_amr)->allocate(deltaE, this->m_fluidRealm, this->m_plasmaPhase, 1);

  // Get the fields in the plasma phase -- the actual field and the background field.
  const MFAMRCellData electricField = (this->m_fieldSolver)->getElectricField();
  const EBAMRCellData poissonField  = (this->m_amr)->alias(this->m_plasmaPhase, electricField);
  const EBAMRCellData laplaceField  = (this->m_amr)->alias(this->m_plasmaPhase, m_backgroundField);

  // Compute the field magnitude, and then the relative change in field magnitude.
  DataOps::vectorLength(poissonNorm, poissonField);
  DataOps::vectorLength(laplaceNorm, laplaceField);

  DataOps::copy(deltaE, poissonNorm);
  DataOps::incr(deltaE, laplaceNorm, -1.0);
  DataOps::divideFallback(deltaE, laplaceNorm, 0.0);

  (this->m_amr)->arithmeticAverage(deltaE, this->m_fluidRealm, this->m_plasmaPhase);
  (this->m_amr)->interpGhost(deltaE, this->m_fluidRealm, this->m_plasmaPhase);

  // Iterate through the grid cells and figure out where the field change the most.
  //
  // PS: I'm doing this with a direct loop because DataOps::getMaxMin will do ALL cells, including ones that are
  //     covered by a finer level. But we only want to evaluate the valid region.
  Real maxChange = 0.0;

  for (int lvl = 0; lvl <= (this->m_amr)->getFinestLevel(); lvl++) {
    const DisjointBoxLayout& dbl   = (this->m_amr)->getGrids(this->m_fluidRealm)[lvl];
    const DataIterator&      dit   = dbl.dataIterator();
    const EBISLayout&        ebisl = (this->m_amr)->getEBISLayout(this->m_fluidRealm, this->m_plasmaPhase)[lvl];

    const int nbox = dit.size();

#pragma omp parallel for schedule(runtime)
    for (int mybox = 0; mybox < nbox; mybox++) {
      const DataIndex&     din        = dit[mybox];
      const Box            box        = dbl[din];
      const EBISBox&       ebisbox    = ebisl[din];
      const BaseFab<bool>& validCells = (*(this->m_amr)->getValidCells(this->m_fluidRealm)[lvl])[din];

      const EBCellFAB& data    = (*deltaE[lvl])[din];
      const FArrayBox& dataReg = data.getFArrayBox();

      auto regularKernel = [&](const IntVect& iv) -> void {
        if (validCells(iv) && ebisbox.isRegular(iv)) {
          maxChange = std::max(maxChange, std::abs(dataReg(iv, 0)));
        }
      };

      auto irregularKernel = [&](const VolIndex& vof) -> void {
        if (validCells(vof.gridIndex()) && ebisbox.isIrregular(vof.gridIndex())) {
          maxChange = std::max(maxChange, std::abs(data(vof, 0)));
        }
      };

      VoFIterator& vofit = (*(this->m_amr)->getVofIterator(this->m_fluidRealm, this->m_plasmaPhase)[lvl])[din];

      BoxLoops::loop(box, regularKernel);
      BoxLoops::loop(vofit, irregularKernel);
    }
  }

  return ParallelOps::max(maxChange);
}

#include <CD_NamespaceFooter.H>

#endif
