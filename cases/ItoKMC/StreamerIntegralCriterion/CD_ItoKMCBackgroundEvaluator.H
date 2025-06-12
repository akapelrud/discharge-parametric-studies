/* chombo-discharge
 * Copyright © 2025 SINTEF Energy Research.
 * Please refer to Copyright.txt and LICENSE in the chombo-discharge root directory.
 */

/*!
  @file   CD_ItoKMCBackgroundEvaluator.H
  @brief  File containing a subclass of ItoKMCGodunovStepper.
  @author Robert Marskar
*/

#ifndef CD_ItoKMCBackgroundEvaluator_H
#define CD_ItoKMCBackgroundEvaluator_H

// Our includes
#include <CD_ItoKMCGodunovStepper.H>
#include <CD_NamespaceHeader.H>

namespace Physics {
  namespace ItoKMC {

    /*!
      @brief Implementation of ItoKMCGodunovStepper that also evaluates the background field at every regrid/time step.
    */
    template <typename I = ItoSolver, typename C = CdrCTU, typename R = McPhoto, typename F = FieldSolverMultigrid>
    class ItoKMCBackgroundEvaluator : public ItoKMCGodunovStepper<I, C, R, F>
    {
    public:
      /*!
	@brief Constructor.
	@param[in] a_physics Physics kernel that will be used. 
      */
      ItoKMCBackgroundEvaluator(RefCountedPtr<ItoKMCPhysics>& a_physics) noexcept;

      /*!
	@brief Post-initialization operations. Computes the background field.
      */
      virtual void
      postInitialize() noexcept override final;

      /*!
	@brief Post-regrid operations. Computes the background field.
      */
      virtual void
      postRegrid() noexcept override final;

      /*!
	@brief Print a new step report. This is the old one plus the maximum field change.
      */
      virtual void
      printStepReport() noexcept override final;

    protected:
      /*!
	@brief Exit criterion -- if the background field changes by this much the simulation is terminated.
      */
      Real m_exitCrit;

      /*!
	@brief For storing the background field.
	@details This field is space- and surface-charge free and is filled by computeBackgroundField
      */
      MFAMRCellData m_backgroundField;

      /*!
	@brief Computes the background field. I.e., it allocates and fills m_backgroundField.
      */
      virtual void
      computeBackgroundField() noexcept;

      /*!
	@brief Evaluate the maximum change in the background field.
      */
      [[nodiscard]]
      virtual Real
      evaluateSpaceChargeEffects() noexcept;
    };
  } // namespace ItoKMC
} // namespace Physics

#include <CD_NamespaceFooter.H>

#include <CD_ItoKMCBackgroundEvaluatorImplem.H>

#endif
