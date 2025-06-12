/* chombo-discharge
 * Copyright © 2024 SINTEF Energy Research.
 * Please refer to Copyright.txt and LICENSE in the chombo-discharge root directory.
 */

/*!
  @file   CD_ItoKMCGodunovStepper.H
  @brief  Declaration of a class which uses a semi-implicit Godunov method for Ito plasma equations
  @author Robert Marskar
*/

#ifndef CD_ItoKMCBackgroundEvaluator_H
#define CD_ItoKMCBackgroundEvaluator_H

// Our includes
#include <CD_ItoKMCStepper.H>
#include <CD_ItoKMCGodunovStepper.H>
#include <CD_LookupTable.H>
#include <CD_DataParser.H>
#include <CD_NamespaceHeader.H>

namespace Physics {
  namespace ItoKMC {

    /*!
      @brief Implementation of ItoKMCStepper that uses a semi-implicit split-step formalism for advancing the Ito-Poisson-KMC system. 
    */
    template <typename I = ItoSolver, typename C = CdrCTU, typename R = McPhoto, typename F = FieldSolverMultigrid>
    class ItoKMCBackgroundEvaluator : public ItoKMCGodunovStepper<I, C, R, F>
    {
    public:
      ItoKMCBackgroundEvaluator(RefCountedPtr<ItoKMCPhysics>& a_physics)
        : ItoKMCGodunovStepper<I, C, R, F>(a_physics)
      {}

    protected:

      /*!
	@brief For storing the background field
      */
      EBAMRCellData m_backgroundField;

      /*!
	@brief Computes the background field
      */
      virtual void computeBackgroundField() noexcept{}
    };
  } // namespace ItoKMC
} // namespace Physics

#include <CD_NamespaceFooter.H>

#include <CD_ItoKMCBackgroundEvaluator.H>

#endif
