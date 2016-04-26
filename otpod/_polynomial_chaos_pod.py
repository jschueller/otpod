# -*- coding: utf-8 -*-
# -*- Python -*-

__all__ = ['PolynomialChaosPOD']

import openturns as ot
import numpy as np
from ._pod import POD
from scipy.interpolate import interp1d
from _decorator import DocInherit, keepingArgs
from ._math_tools import computeR2
import matplotlib.pyplot as plt
import logging

class PolynomialChaosPOD(POD):
    """
    Polynomial chaos based POD.

    **Available constructor:**

    PolynomialChaosPOD(*inputSample, outputSample, detection, noiseThres,
    saturationThres, boxCox*)

    Parameters
    ----------
    inputSample : 2-d sequence of float
        Vector of the input values. The first column must correspond with the
        defect sizes.
    outputSample : 2-d sequence of float
        Vector of the signals, of dimension 1.
    detection : float
        Detection value of the signal.
    noiseThres : float
        Value for low censored data. Default is None.
    saturationThres : float
        Value for high censored data. Default is None
    boxCox : bool or float
        Enable or not the Box Cox transformation. If boxCox is a float, the Box
        Cox transformation is enabled with the given value. Default is False.

    Warning
    -------
    The first column of the input sample must corresponds with the defects sample.

    Notes
    -----
    This class aims at building the POD based on a polynomial chaos model. The
    return POD model corresponds with an interpolate function built
    with the POD values computed for the given defect sizes. The default values
    are 20 defect sizes between the minimum and maximum value of the defect sample.
    The defect sizes can be changed using the method *setDefectSizes*.

    The default polynomial chaos model is built with uniform distributions for
    each parameters. Coefficients are computed using the LAR algorithm combined
    with the KFold. The AdaptiveStrategy is chosen fixed with a linear enumerate
    function of maximum degree 5.

    For advanced use, all parameters can be defined thanks to dedicated set 
    methods. Moreover, if the user has already built a polynomial chaos result, 
    it can be given as parameter using the method *setPolynomialChaosResult*,
    then the POD are computed based on this polynomial chaos result.
    """

    def __init__(self, inputSample=None, outputSample=None, detection=None, noiseThres=None,
                 saturationThres=None, boxCox=False):

        # initialize the POD class
        super(PolynomialChaosPOD, self).__init__(inputSample, outputSample,
                                 detection, noiseThres, saturationThres, boxCox)
        # inherited attributes
        # self._simulationSize
        # self._detection
        # self._inputSample
        # self._outputSample
        # self._noiseThres
        # self._saturationThres        
        # self._lambdaBoxCox
        # self._boxCox
        # self._size
        # self._dim
        # self._censored

        self._chaosResult = None
        self._samplingSize = 1000
        self._distribution = None
        self._adaptiveStrategy = None
        self._projectionStrategy = None
        # define the defect sizes for the interpolation function
        self._defectNumber = 20
        self._defectSizes = np.linspace(self._inputSample[:,0].getMin()[0], 
                                  self._inputSample[:,0].getMax()[0],
                                  self._defectNumber)

        self._normalDist = ot.Normal()

        if self._censored:
            logging.info('Censored data are not taken into account : the quantile ' + \
                         'regression model is only performed on filtered data.')

    def run(self):
        """
        Build the POD models.

        Notes
        -----
        This method build the quantile regression model. First the censored data
        are filtered if needed. The Box Cox transformation is performed if it is
        enabled. Then it builds the POD model for given data and computes using
        bootstrap all the defects quantile needed to build the POD model at the
        confidence level.
        """

        # Run the preliminary run of the POD class
        result = self._run(self._inputSample, self._outputSample, self._detection,
                           self._noiseThres, self._saturationThres, self._boxCox,
                           self._censored)

        # get some results
        self._inputSample = result['inputSample']
        self._signals = result['signals']
        self._detectionBoxCox = result['detectionBoxCox']
        inputSize = self._inputSample.getSize()

        # run the chaos algorithm and get result if not given
        if self._chaosResult is None:
            self._algoChaos = self._buildChaosModel(self._inputSample, self._signals)
            self._algoChaos.run()
            self._chaosResult = self._algoChaos.getResult()

        # get the metamodel
        self._chaosPred = self._chaosResult.getMetaModel()
        # get the basis, coef and transformation, needed for the confidence interval
        self._chaosCoefs = self._chaosResult.getCoefficients()
        self._reducedBasis = self._chaosResult.getReducedBasis()
        self._transformation = self._chaosResult.getTransformation()

        # compute the residuals and stderr
        basisSize = self._reducedBasis.getSize()
        self._residuals = self._signals - self._chaosPred(self._inputSample) # residuals
        self._stderr = np.sqrt(np.sum(np.array(self._residuals)**2) / (inputSize - basisSize - 1))

        # Compute the POD values for each defect sizes
        POD = self._computePOD(self._defectSizes, self._chaosCoefs)
        # create the interpolate function
        interpModel = interp1d(self._defectSizes, POD, kind='linear')
        self._PODmodel = ot.PythonFunction(1, 1, interpModel)

        ####################### confidence interval ############################
        self._basisFunction = ot.NumericalMathFunction(ot.NumericalMathFunction(
                                self._reducedBasis), self._transformation)
        dof = inputSize - basisSize - 1
        varEpsilon = (ot.ChiSquare(dof).inverse() * dof * self._stderr**2).getRealization()[0]
        gramBasis = ot.Matrix(self._basisFunction(self._inputSample)).computeGram()
        covMatrix = gramBasis.solveLinearSystem(ot.IdentityMatrix(basisSize)) * varEpsilon
        coefsDist = ot.Normal(np.hstack(self._chaosCoefs), ot.CovarianceMatrix(covMatrix.getImplementation()))
        coefsRandom = coefsDist.getSample(self._simulationSize)

        self._PODPerDefect = ot.NumericalSample(self._simulationSize, self._defectNumber)
        for i, coefs in enumerate(coefsRandom):
            self._PODPerDefect[i, :] = self._computePOD(self._defectSizes, coefs)


    def getPODModel(self):
        """
        Accessor to the POD model.

        Returns
        -------
        PODModel : :py:class:`openturns.NumericalMathFunction`
            The function which computes the probability of detection for a given
            defect value.
        """
        return self._PODmodel

    def getPODCLModel(self, confidenceLevel=0.95):
        """
        Accessor to the POD model at a given confidence level.

        confidenceLevel : float
            The confidence level the POD must be computed. Default is 0.95

        Returns
        -------
        PODModelCl : :py:class:`openturns.NumericalMathFunction`
            The function which computes the probability of detection for a given
            defect value at the confidence level given as parameter.
        """
        # Compute the quantile at the given confidence level for each
        # defect quantile and build the interpolate function.
        PODQuantile = self._PODPerDefect.computeQuantilePerComponent(
                                                            1. - confidenceLevel)
        interpModel = interp1d(self._defectSizes, PODQuantile, kind='linear')
        PODmodelCl = ot.PythonFunction(1, 1, interpModel)

        return PODmodelCl

    @DocInherit # decorator to inherit the docstring from POD class
    @keepingArgs # decorator to keep the real signature
    def computeDetectionSize(self, probabilityLevel, confidenceLevel=None):
        return self._computeDetectionSize(self.getPODModel(),
                                          self.getPODCLModel(confidenceLevel),
                                          probabilityLevel,
                                          confidenceLevel,
                                          np.min(self._defectSizes),
                                          np.max(self._defectSizes))

    @DocInherit # decorator to inherit the docstring from POD class
    @keepingArgs # decorator to keep the real signature
    def drawPOD(self, probabilityLevel=None, confidenceLevel=None, defectMin=None,
                defectMax=None, nbPt=100, name=None):

        if defectMin is None:
            defectMin = np.min(self._defectSizes)
        else:
            if defectMin < np.min(self._defectSizes):
                raise ValueError('DefectMin must be greater than the minimum ' + \
                                 'of the given defect sizes.')
            if defectMin > np.max(self._defectSizes):
                raise ValueError('DefectMin must be lower than the maximum ' + \
                                 'of the given defect sizes.')
        if defectMax is None:
            defectMax = np.max(self._defectSizes)
        else:
            if defectMax > np.max(self._defectSizes):
                raise ValueError('DefectMax must be lower than the maximum ' + \
                                 'of the given defect sizes.')
            if defectMax < np.min(self._defectSizes):
                raise ValueError('DefectMax must be greater than the maximum ' + \
                                 'of the given defect sizes.')

        if confidenceLevel is None:
            fig, ax = self._drawPOD(self.getPODModel(), None,
                                probabilityLevel, confidenceLevel, defectMin,
                                defectMax, nbPt, name)
        elif confidenceLevel is not None:
            fig, ax = self._drawPOD(self.getPODModel(), self.getPODCLModel(confidenceLevel),
                    probabilityLevel, confidenceLevel, defectMin,
                    defectMax, nbPt, name)

        ax.set_title('POD - Polynomial chaos model')
        if name is not None:
            fig.savefig(name, bbox_inches='tight', transparent=True)

        return fig, ax

    def drawPolynomialChaosModel(self, name=None):
        """
        Draw the polynomial chaos prediction versus the true data.

        Parameters
        ----------
        probabilityLevel : float
            The probability level for which the quantile regression is performed
        name : string
            name of the figure to be saved with *transparent* option sets to True
            and *bbox_inches='tight'*. It can be only the file name or the 
            full path name. Default is None.

        Returns
        -------
        fig : `matplotlib.figure <http://matplotlib.org/api/figure_api.html>`_
            Matplotlib figure object.
        ax : `matplotlib.axes <http://matplotlib.org/api/axes_api.html>`_
            Matplotlib axes object.

        Notes
        -----
        This method only works if the dimension of the input sample is 1.
        """

        model = self._chaosPred

        defects = self._inputSample
        signals = self._signals
        defectsSorted = defects.sort()
        fittedSignals = model(defectsSorted)

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.plot(defects, signals, 'b.', label='Data', ms=9)
        ax.plot(defectsSorted, fittedSignals, 'r-', label='Polynomial chaos model')
        ax.set_xlabel('Defects')
        ax.set_ylabel('Signals')
        ax.set_title('Polynomial chaos model versus data')
        ax.grid()
        ax.legend(loc='upper left')

        if name is not None:
            fig.savefig(name, bbox_inches='tight', transparent=True)

        return fig, ax

    def getR2(self):
        """
        Accessor to the R2 value. 

        Returns
        -------
        R2 : float
            The R2 value.
        """
        return computeR2(self._signals, self._residuals)

    def getQ2(self):
        """
        Accessor to the Q2 value. 

        Returns
        -------
        Q2 : float
            The Q2 value computed analytically.
        """
        basisMatrix = ot.Matrix(self._basisFunction(self._inputSample))
        gramBasis = basisMatrix.computeGram()
        H = basisMatrix * gramBasis.solveLinearSystem(basisMatrix.transpose())
        Hdiag = np.vstack(np.array(H).diagonal())
        fittedSignals = np.array(self._chaosPred(self._inputSample))
        delta = (self._signals - fittedSignals) / (1. - Hdiag)

        return 1 - np.mean(delta**2)/ self._signals.computeVariance()[0]

    def getSamplingSize(self):
        """
        Accessor to the Monte Carlo sampling size.
        """
        return self._samplingSize

    def setSamplingSize(self, size):
        """
        Accessor to the Monte Carlo sampling size.

        Parameters
        ----------
        size : int
            The size of the Monte Carlo simulation used to compute the POD for
            each defect size.
        """
        self._samplingSize = size

    def getDefectSizes(self):
        """
        Accessor to the defect size where POD is computed.
        """
        return self._defectSizes

    def setDefectSizes(self, size):
        """
        Accessor to the defect size where POD is computed.

        Parameters
        ----------
        defectSize : sequence of float
            The defect sizes where the Monte Carlo simulation is performed to
            compute the POD.
        """
        size = np.hstack(np.array(size))
        size.sort()
        self._defectSizes = size.copy()
        self._defectNumber = self._defectSizes.shape[0]

    def setDistribution(self, distribution):
        """
        Accessor to the parameters distribution. 

        Parameters
        -------
        distribution : :py:class:`openturns.ComposedDistribution`
            The input parameters distribution.
        """
        try:
            ot.ComposedDistribution(distribution)
        except NotImplementedError:
            raise Exception('The given parameter is not a ComposedDistribution.')
        self._distribution = distribution

    def getDistribution(self):
        """
        Accessor to the parameters distribution. 

        Returns
        -------
        distribution : :py:class:`openturns.ComposedDistribution`
            The input parameters distribution, default is a Uniform distribution
            for all parameters.
        """
        if self._distribution is None:
            print 'The run method must be launched first.'
        else:
            return self._distribution

    def setAdaptiveStrategy(self, strategy):
        """
        Accessor to the adaptive strategy. 

        Parameters
        -------
        strategy : :py:class:`openturns.AdaptiveStrategy`
            The adaptive strategy for the polynomial chaos.
        """
        try:
            ot.AdaptiveStrategy(strategy)
        except NotImplementedError:
            raise Exception('The given parameter is not an AdaptiveStrategy.')
        self._adaptiveStrategy = strategy

    def getAdaptiveStrategy(self):
        """
        Accessor to the adaptive strategy.

        Returns
        -------
        strategy : :py:class:`openturns.AdaptiveStrategy`
            The adaptive strategy for the polynomial chaos.
        """
        if self._adaptiveStrategy is None:
            print 'The run method must be launched first.'
        else:
            return self._adaptiveStrategy

    def setProjectionStrategy(self, strategy):
        """
        Accessor to the projection strategy. 

        Parameters
        -------
        strategy : :py:class:`openturns.ProjectionStrategy`
            The projection strategy for the polynomial chaos.
        """
        try:
            ot.ProjectionStrategy(strategy)
        except NotImplementedError:
            raise Exception('The given parameter is not an ProjectionStrategy.')
        self._projectionStrategy = strategy

    def getProjectionStrategy(self):
        """
        Accessor to the projection strategy.

        Returns
        -------
        strategy : :py:class:`openturns.ProjectionStrategy`
            The projection strategy for the polynomial chaos.
        """
        if self._projectionStrategy is None:
            print 'The run method must be launched first.'
        else:
            return self._projectionStrategy

    def setPolynomialChaosResult(self, chaosResult):
        """
        Accessor to the polynomial chaos result.

        Parameters
        -------
        chaosResult : :py:class:`openturns.FunctionalChaosResult`
            The polynomial chaos result.
        """
        try:
            ot.FunctionalChaosResult(chaosResult)
        except NotImplementedError:
            raise Exception('The given parameter is not an FunctionalChaosResult.')
        self._chaosResult = chaosResult

    def getPolynomialChaosResult(self):
        """
        Accessor to the polynomial chaos result.

        Returns
        -------
        result : :py:class:`openturns.FunctionalChaosResult`
            The polynomial chaos result.
        """
        if self._chaosResult is None:
            print 'The run method must be launched first.'
        else:
            return self._chaosResult


    def _buildChaosModel(self, inputSample, outputSample):
        """
        Build the functional chaos algorithm without running it.
        """
        if self._distribution is None:
            # create default distribution : Uniform between min and max of the 
            # input sample
            inputSample = ot.NumericalSample(inputSample)
            inputMin = inputSample.getMin()
            inputMax = inputSample.getMax()
            marginals = [ot.Uniform(inputMin[i], inputMax[i]) for i in range(self._dim)]
            self._distribution = ot.ComposedDistribution(marginals)

        # put description of the inputSample into decription of the distribution
        self._distribution.setDescription(inputSample.getDescription())

        if self._adaptiveStrategy is None:
            # Create the adaptive strategy : default is fixed strategy of degree 5
            # with linear enumerate function
            polyCol = [0.]*self._dim
            for i in range(self._dim):
                polyCol[i] = ot.StandardDistributionPolynomialFactory(
                                                self._distribution.getMarginal(i))
            
            enumerateFunction = ot.EnumerateFunction(self._dim)
            multivariateBasis = ot.OrthogonalProductPolynomialFactory(polyCol, enumerateFunction)
            # max degree 5
            p = 5
            indexMax = enumerateFunction.getStrataCumulatedCardinal(p)
            self._adaptiveStrategy = ot.FixedStrategy(multivariateBasis, indexMax)

        if self._projectionStrategy is None:
            # sparse polynomial chaos
            basis_sequence_factory = ot.LAR()
            fitting_algorithm = ot.KFold()
            approximation_algorithm = ot.LeastSquaresMetaModelSelectionFactory(
                                      basis_sequence_factory, fitting_algorithm)
            self._projectionStrategy = ot.LeastSquaresStrategy(inputSample,
                                        outputSample, approximation_algorithm)

        return ot.FunctionalChaosAlgorithm(inputSample, outputSample, \
                self._distribution, self._adaptiveStrategy, self._projectionStrategy)


    def _mergeDefectInX(self, defect, X):
        """
        defect : scalar of the defect value
        X : sample without the defect column
        """
        size = X.getSize()
        dim = X.getDimension() + 1
        samplePred = ot.NumericalSample(size, dim)
        samplePred[:, 0] = ot.NumericalSample(size, [defect])
        samplePred[:, 1:] = X
        return samplePred


    def _buildChaosFunction(self, reducedBasis, transformation, coefs):
        """
        Build the chaos metamodel with given coefficients.
        """
        standardChaosFunction = ot.NumericalMathFunction(reducedBasis, coefs)
        chaosFunction = ot.NumericalMathFunction(standardChaosFunction, transformation)
        return chaosFunction


    def _computePOD(self, defectSizes, coefs):
        """
        Compute the POD for all defect sizes in vectorized way.
        """
        # create the input sample that must be computed by the metamodels
        samplePred = self._distribution.getSample(self._samplingSize)[:,1:]
        fullSamplePred = ot.NumericalSample(self._samplingSize * self._defectNumber, 1)
        for i, defect in enumerate(defectSizes):
            fullSamplePred[self._samplingSize*i:self._samplingSize*(i+1)] = \
                                    self._mergeDefectInX(defect, samplePred)

        # create the chaos function for user defined coefs
        chaosFunction = self._buildChaosFunction(self._reducedBasis,
                                        self._transformation, coefs)

        # add the randomness from the residuals
        residualsSample = self._normalDist.getSample(self._samplingSize * \
                                             self._defectNumber) * self._stderr
        chaosRandomSample = chaosFunction(fullSamplePred) + residualsSample

        # compute the POD for all defect sizes
        POD = [1.*len(np.where(np.array(chaosRandomSample[self._samplingSize \
                    * i:self._samplingSize*(i+1)]) > self._detectionBoxCox)[0]) \
                    / self._samplingSize for i in xrange(self._defectNumber)]

        return POD