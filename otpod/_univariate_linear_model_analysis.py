# -*- coding: utf-8 -*-
# -*- Python -*-

__all__ = ['UnivariateLinearModelAnalysis']

import openturns as ot
from ._math_tools import computeBoxCox, computeZeroMeanTest, computeBreuschPaganTest, \
                         computeHarrisonMcCabeTest, computeDurbinWatsonTest, \
                         computeR2, censureFilter, computeLinearParametersCensored
from statsmodels.regression.linear_model import OLS
import numpy as np

class UnivariateLinearModelAnalysis():

    """
    Linear regression analysis with residuals hypothesis tests.
    
    **Available constructors**

    UnivariateLinearModelAnalysis(*inputSample, outputSample*)

    UnivariateLinearModelAnalysis(*inputSample, outputSample, noiseThres,
    saturationThres, resDistFact, boxCox*)

    Parameters
    ----------
    inputSample : 2-d sequence of float
        Vector of the defect sizes, of dimension 1.
    outputSample : 2-d sequence of float
        Vector of the signals, of dimension 1.
    noiseThres : float
        Value for low censored data. Default is None.
    saturationThres : float
        Value for high censored data. Default is None
    resDistFact : :py:class:`openturns.DistributionFactory`
        Distribution hypothesis followed by the residuals. Default is 
        :py:class:`openturns.NormalFactory`.
    boxCox : bool or float
        Enable or not the Box Cox transformation. If boxCox is a float, the Box
        Cox transformation is enabled with the given value. Default is False.

    Notes
    -----
    This method automatically :

    - Computes the Box Cox parameter if *boxCox* is True,
    - Computes the transformed signals if *boxCox* is True or a float,
    - Builds the univariate linear regression model on the data,
    - Computes the linear regression parameters for censored data if needed,
    - Computes the residuals,
    - Runs all hypothesis tests.
    """

    class _Results():
        """
        This class contains the result of the analysis. Instances are created
        for uncensored data or if needed for censored data.
        """
        def __init__(self):
            self.intercept = None
            self.slope = None
            self.stderr = None
            self.confInt = None
            self.testResults = None

    def __init__(self, inputSample, outputSample, noiseThres=None,
                 saturationThres=None, resDistFact=ot.NormalFactory(),
                 boxCox=False):

        self._inputSample = ot.NumericalSample(np.vstack(inputSample))
        self._outputSample = ot.NumericalSample(np.vstack(outputSample))
        self._noiseThres = noiseThres
        self._saturationThres = saturationThres
        # Add flag to tell if censored data must taken into account or not.
        if noiseThres is not None or saturationThres is not None:
            # flag to tell censoring is enabled
            self._censored = True
            # Results instances are created for both cases.
            self._resultsCens = self._Results()
            self._resultsUnc = self._Results()
        else:
            self._censored = False
            # Results instance is created only for uncensored case.
            self._resultsUnc = self._Results()

        self._resDistFact = resDistFact

        # if Box Cox is a float the transformation is enabled with the given value
        if type(boxCox) is float:
            self._lambdaBoxCox = boxCox
            self._boxCox = True
        else:
            self._lambdaBoxCox = None
            self._boxCox = boxCox

        self._size = self._inputSample.getSize()
        self._dim = self._inputSample.getDimension()

        # Assertions on parameters
        assert (self._size >=3), "Not enough observations."
        assert (self._size == self._outputSample.getSize()), \
                "InputSample and outputSample must have the same size."
        assert (self._dim == 1), "InputSample must be of dimension 1."
        assert (self._outputSample.getDimension() == 1), "OutputSample must be of dimension 1."

        # run the analysis
        self._run()

    def _run(self):
        """
        Run the analysis :
        - Computes the Box Cox parameter if *boxCox* is True,
        - Computes the transformed signals if *boxCox* is True or a float,
        - Builds the univariate linear regression model on the data,
        - Computes the linear regression parameters for censored data if needed,
        - Computes the residuals,
        - Runs all hypothesis tests.
        """

        #################### Filter censored data ##############################
        if self._censored:
            # check if one sided censoring
            if self._noiseThres is None:
                noiseThres = -ot.sys.float_info.max
            else:
                noiseThres = self._noiseThres
            if self._saturationThres is None:
                saturationThres = ot.sys.float_info.max
            else:
                saturationThres = self._saturationThres
            # Filter censored data
            # Returns:
            # defects in the non censored area
            # defectsNoise in the noisy area
            # defectsSat in the saturation area
            # signals in the non censored area
            # check if one the threshold is None
            defects, defectsNoise, defectsSat, signals = \
                censureFilter(self._inputSample, self._outputSample,
                              noiseThres, saturationThres)
        else:
            defects, signals = self._inputSample, self._outputSample
        
        defectsSize = defects.getSize()

        ###################### Box Cox transformation ##########################
        # Compute Box Cox if enabled
        if self._boxCox:
            if self._lambdaBoxCox is None:
                # optimization required
                self._lambdaBoxCox = computeBoxCox(defects, signals)

            # Transformation of data
            boxCoxTransform = ot.BoxCoxTransform([self._lambdaBoxCox])
            signals = boxCoxTransform(signals)
            if self._noiseThres is not None:
                noiseThres = boxCoxTransform([self._noiseThres])[0]
            if self._saturationThres is not None:
                saturationThres = boxCoxTransform([self._saturationThres])[0]
        else:
            noiseThres = self._noiseThres
            saturationThres = self._saturationThres

        ######################### Linear Regression model ######################
        # Linear regression with statsmodels module
        # Create the X matrix : [1, inputSample]
        X = ot.NumericalSample(defectsSize, [1, 0])
        X[:, 1] = defects
        algoLinear = OLS(np.array(signals), np.array(X)).fit()
        self._resultsUnc.intercept = algoLinear.params[0]
        self._resultsUnc.slope = algoLinear.params[1]
        # get standard error estimates (residuals standard deviation)
        self._resultsUnc.stderr = np.sqrt(algoLinear.scale)
        # get confidence interval at level 95%
        self._resultsUnc.confInt = algoLinear.conf_int(0.05)

        if self._censored:
            # define initial starting point for MLE optimization
            initialStartMLE = [self._resultsUnc.intercept, self._resultsUnc.slope,
                               self._resultsUnc.stderr]
            # MLE optimization
            res = computeLinearParametersCensored(initialStartMLE, defects,
                defectsNoise, defectsSat, signals, noiseThres, saturationThres)
            self._resultsCens.intercept = res[0]
            self._resultsCens.slope = res[1]
            self._resultsCens.stderr = res[2]

        ############################ Residuals #################################
        # get residuals from algoLinear
        self._resultsUnc.residuals = ot.NumericalSample(np.vstack(algoLinear.resid))
        # compute residuals distribution
        self._resultsUnc.resDist = self._resDistFact.build(self._resultsUnc.residuals)

        if self._censored:
            # create linear model function
            def CensLinModel(x):
                return self._resultsCens.intercept + self._resultsCens.slope * x

            # compute the residuals for the censored case.
            self._resultsCens.residuals = signals - CensLinModel(defects)
            # compute residuals distribution.
            self._resultsCens.resDist = self._resDistFact.build(self._resultsCens.residuals)

        ########################## Compute tests ###############################
        self._resultsUnc.testResults = \
                self._computeTests(defects, signals, self._resultsUnc.residuals,
                                   self._resultsUnc.resDist)

        if self._censored:
            self._resultsCens.testResults = \
                self._computeTests(defects, signals, self._resultsCens.residuals,
                                   self._resultsCens.resDist)

        ################ Build the result lists to be printed ##################
        self._buildPrintResults()


################################################################################
###################### Hypothesis and validation tests #########################
################################################################################

    def _computeTests(self, defects, signals, residuals, resDist):

        testResults = {}
        # compute R2
        testResults['R2'] = computeR2(signals, residuals)

        # compute Anderson Darling test (normality test)
        testAnderDar = ot.NormalityTest.AndersonDarlingNormal(residuals)
        testResults['AndersonDarling'] = testAnderDar.getPValue()

        # compute Cramer Von Mises test (normality test)
        testCramVM = ot.NormalityTest.CramerVonMisesNormal(residuals)
        testResults['CramerVonMises'] = testCramVM.getPValue()

        # compute zero residual mean test
        testResults['ZeroMean'] = computeZeroMeanTest(residuals)

        # compute Kolmogorov test (fitting test)
        testKol = ot.FittingTest.Kolmogorov(residuals, resDist, 0.95,
                                            resDist.getParametersNumber())
        testResults['Kolmogorov'] = testKol.getPValue()

        # compute Breusch Pagan test (homoskedasticity : constant variance)
        testResults['BreuschPagan'] = computeBreuschPaganTest(defects, residuals)

        # compute Harrison McCabe test (homoskedasticity : constant variance)
        testResults['HarrisonMcCabe'] = computeHarrisonMcCabeTest(residuals)

        # compute Durbin Watson test (autocorrelation == 0)
        testResults['DurbinWatson'] = computeDurbinWatsonTest(defects, residuals)

        return testResults

################################################################################
########################## Print and saving results ############################
################################################################################

    def printResults(self):
        """ Print results of the linear analysis.
        """
        # Enable warning to be displayed
        ot.Log.Show(ot.Log.WARN)

        regressionResult = '\n'.join(['{:<45} {:>13} {:>13}'.format(*line) for
                            line in self._dataRegression])

        residualsResult = '\n'.join(['{:<45} {:>13} {:>13}'.format(*line) for 
                            line in self._dataResiduals])

        ndash = 80
        print '-' * ndash
        print '         Linear model analysis results'
        print '-' * ndash
        print regressionResult
        print '-' * ndash
        print ''
        print '-' * ndash
        print '         Residuals analysis results'
        print '-' * ndash
        print residualsResult
        print '-' * ndash

        # print warnings
        self._printWarnings()

    def _printWarnings(self):
        # Check results and display warnings

        valuesUnc = np.array(self._resultsUnc.testResults.values())
        if self._censored:
            valuesCens = np.array(self._resultsCens.testResults.values())
            testPValues = ((valuesUnc < 0.05).any() or (valuesCens < 0.05).any())
        else:
            testPValues = (valuesUnc < 0.05).any()

        # print warning if some pValues are less than 0.05
        msg = ["", "", ""]
        if testPValues and not self._boxCox:
            msg[0] = 'Some hypothesis tests failed : please consider to use '+\
                        'the Box Cox transformation.'
            ot.Log.Warn(msg[0])
            ot.Log.Flush()
        elif testPValues and self._boxCox:
            msg[1] = 'Some hypothesis tests failed : please consider to use '+\
                        'quantile regression or polynomial chaos to build POD.'
            ot.Log.Warn(msg[1])
            ot.Log.Flush()

        if self._resultsUnc.resDist.getClassName() != 'Normal':
            msg[2] = 'Confidence interval, Normality tests and zero ' + \
                        'residual mean test are given assuming the residuals ' +\
                        'follow a Normal distribution.'
            ot.Log.Warn(msg[2])
            ot.Log.Flush()
        # return msg the test with pytest
        return msg

    def saveResults(self, pathname):
        """
        Save all analysis test results in a file.

        Parameters
        ----------
        pathname : string
            Name of the file or full path name.

        Notes
        -----
        The file can be saved as a csv file. Separations are made with tabulations.

        If *pathname* is the file name, then it is saved in the current working
        directory.
        """
        regressionResult = '\n'.join(['{}\t{}\t{}'.format(*line) for
                                line in self._dataRegression])

        residualsResult = '\n'.join(['{}\t{}\t{}'.format(*line) for
                                line in self._dataResiduals])

        with open(pathname, 'w') as fd:
            fd.write('Linear model analysis results\n\n')
            fd.write(regressionResult)
            fd.write('\n\nResiduals analysis results\n\n')
            fd.write(residualsResult)

    def _buildPrintResults(self):
        # Build the lists used in the printResult and saveResults methods :
        # self._dataRegression
        # self._dataResiduals

        # number of digits to be displayed
        n_digits = 2
        #format for confidence interval
        strformat =  "[{:0."+str(n_digits)+"f}, {:0."+str(n_digits)+"f}]"

        if self._boxCox:
            boxCoxstr = round(self._lambdaBoxCox, n_digits)
        else:
            boxCoxstr = "Not enabled"

        testResults = self._resultsUnc.testResults

        # create lists containing all results
        self._dataRegression = [
            ["Box Cox parameter :", boxCoxstr, ""],
            ["", "", ""],
            ["", "Uncensored", ""],
            ["", "", ""],
            ["Intercept coefficient :", round(self._resultsUnc.intercept, n_digits), ""],
            ["Slope coefficient :", round(self._resultsUnc.slope, n_digits), ""],
            ["Standard error of the estimate :", round(self._resultsUnc.stderr, n_digits), ""],
            ["", "", ""],
            ["Confidence interval on coefficients", "", ""],
            ["Intercept coefficient :", strformat.format(*self._resultsUnc.confInt[0]), ""],
            ["Slope coefficient :", strformat.format(*self._resultsUnc.confInt[1]), ""],
            ["Level :", 0.95, ""],
            ["", "", ""],
            ["Quality of regression", "", ""],
            ["R2 (> 0.8):", round(self._resultsUnc.testResults['R2'], n_digits), ""]]

        self._dataResiduals = [
            ["Fitted distribution (uncensored) :", self._resultsUnc.resDist.__str__(), ""],
            ["", "", ""],
            ["", "Uncensored", ""],
            ["Distribution fitting test", "", ""],
            ["Kolmogorov p-value (> 0.05):", round(testResults['Kolmogorov'], n_digits), ""],
            ["", "", ""],
            ["Normality test", "", ""],
            ["Anderson Darling p-value (> 0.05):", round(testResults['AndersonDarling'], n_digits), ""],
            ["Cramer Von Mises p-value (> 0.05):", round(testResults['CramerVonMises'], n_digits), ""],
            ["", "", ""],
            ["Zero residual mean test", "", ""],
            ["p-value (> 0.05):", round(testResults['ZeroMean'], n_digits), ""],
            ["", "", ""],
            ["Homoskedasticity test (constant variance)", "", ""],
            ["Breush Pagan p-value (> 0.05):", round(testResults['BreuschPagan'], n_digits), ""],
            ["Harrison McCabe p-value (> 0.05):", round(testResults['HarrisonMcCabe'], n_digits), ""],
            ["", "", ""],
            ["Non autocorrelation test", "", ""],
            ["Durbin Watson p-value (> 0.05):", round(testResults['DurbinWatson'], n_digits), ""]]

        if self._censored:
            # Add censored case results in the lists
            testResults = self._resultsCens.testResults

            self._dataRegression[2][2] = "Censored"
            self._dataRegression[4][2] = round(self._resultsCens.intercept, n_digits)
            self._dataRegression[5][2] = round(self._resultsCens.slope, n_digits)
            self._dataRegression[6][2] = round(self._resultsCens.stderr, n_digits)
            self._dataRegression[14][2] = round(self._resultsCens.testResults['R2'], n_digits)

            self._dataResiduals.insert(1, ["Fitted distribution (censored) :",
                                       self._resultsCens.resDist.__str__(), ""])
            self._dataResiduals[3][2] = "Censored"
            self._dataResiduals[5][2] = round(testResults['Kolmogorov'], n_digits)
            self._dataResiduals[8][2] = round(testResults['AndersonDarling'], n_digits)
            self._dataResiduals[9][2] = round(testResults['CramerVonMises'], n_digits)
            self._dataResiduals[12][2] = round(testResults['ZeroMean'], n_digits)
            self._dataResiduals[15][2] = round(testResults['BreuschPagan'], n_digits)
            self._dataResiduals[16][2] = round(testResults['HarrisonMcCabe'], n_digits)
            self._dataResiduals[19][2] = round(testResults['DurbinWatson'], n_digits)


################################################################################
###################### get methods #############################################
################################################################################

    def getResiduals(self):
        """
        Accessor to the residuals. 

        Returns
        -------
        residuals : :py:class:`openturns.NumericalSample`
            The residuals computed from the uncensored and censored linear
            regression model. The first column corresponds with the uncensored case.
        """
        size = self._resultsUnc.residuals.getSize()
        if self._censored:
            residuals = ot.NumericalSample(size, 2)
            residuals[:, 0] = self._resultsUnc.residuals
            residuals[:, 1] = self._resultsCens.residuals
            residuals.setDescription(['Residuals for uncensored case',
                                      'Residuals for censored case'])
        else:
            residuals = self._resultsUnc.residuals
            residuals.setDescription(['Residuals for uncensored case'])

        return residuals

    def getResidualsDistribution(self):
        """
        Accessor to the residuals distribution. 

        Returns
        -------
        distribution : list of :py:class:`openturns.Distribution`
            The fitted distribution on the residuals, computed in the uncensored
            and censored (if so) case.
        """
        distribution = [self._resultsUnc.resDist]
        if self._censored:
            distribution.append(self._resultsCens.resDist)
        return distribution

    def getIntercept(self):
        """
        Accessor to the intercept parameter of the linear regression model. 

        Returns
        -------
        intercept : :py:class:`openturns.NumericalPoint`
            The intercept parameter for the uncensored and censored (if so) linear
            regression model.
        """
        if self._censored:
            intercept = ot.NumericalPointWithDescription(
                        [('Intercept for uncensored case', 
                        self._resultsUnc.intercept),
                        ('Intercept for censored case',
                        self._resultsCens.intercept)])
        else:
            intercept = ot.NumericalPointWithDescription(
                        [('Intercept for uncensored case', 
                        self._resultsUnc.intercept)])

        return intercept

    def getSlope(self):
        """
        Accessor to the slope parameter of the linear regression model. 

        Returns
        -------
        slope : :py:class:`openturns.NumericalPoint`
            The slope parameter for the uncensored and censored (if so) linear
            regression model.
        """
        if self._censored:
            slope = ot.NumericalPointWithDescription(
                        [('Slope for uncensored case', 
                        self._resultsUnc.slope),
                        ('Slope for censored case',
                        self._resultsCens.slope)])
        else:
            slope = ot.NumericalPointWithDescription(
                        [('Slope for uncensored case', 
                        self._resultsUnc.slope)])

        return slope

    def getStandardError(self):
        """
        Accessor to the standard error of the estimate. 

        Returns
        -------
        stderr : :py:class:`openturns.NumericalPoint`
            The standard error of the estimate for the uncensored and censored
            (if so) linear regression model.
        """
        if self._censored:
            stderr = ot.NumericalPointWithDescription(
                        [('Stderr for uncensored case', 
                        self._resultsUnc.stderr),
                        ('Stderr for censored case',
                        self._resultsCens.stderr)])
        else:
            stderr = ot.NumericalPointWithDescription(
                        [('Stderr for uncensored case', 
                        self._resultsUnc.stderr)])

        return stderr

    def getBoxCoxParameter(self):
        """
        Accessor to the Box Cox parameter. 

        Returns
        -------
        lambdaBoxCox : float
            The Box Cox parameter used to transform the data. If the transformation
            is not enabled None is returned. 
        """
        return self._lambdaBoxCox

    def getR2(self):
        """
        Accessor to the R2 value. 

        Returns
        -------
        R2 : :py:class:`openturns.NumericalPoint`
            Either the R2 for the uncensored case or for both cases.
        """
        return self._getResultValue('R2', 'R2')

    def getAndersonDarlingPValue(self):
        """
        Accessor to the Anderson Darling test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('AndersonDarling', 'Anderson Darling p-value')


    def getCramerVonMisesPValue(self):
        """
        Accessor to the Cramer Von Mises test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('CramerVonMises', 'Cramer Von Mises p-value')

    def getKolmogorovPValue(self):
        """
        Accessor to the Kolmogorov test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('Kolmogorov', 'Kolmogorov p-value')

    def getZeroMeanPValue(self):
        """
        Accessor to the Zero Mean test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('ZeroMean', 'Zero Mean p-value')

    def getBreuschPaganPValue(self):
        """
        Accessor to the Breusch Pagan test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('BreuschPagan', 'Breusch Pagan p-value')

    def getHarrisonMcCabePValue(self):
        """
        Accessor to the Harrison McCabe test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('HarrisonMcCabe', 'Harrison McCabe p-value')

    def getDurbinWatsonPValue(self):
        """
        Accessor to the Durbin Watson test p-value.

        Returns
        -------
        pValue : :py:class:`openturns.NumericalPoint`
            Either the p-value for the uncensored case or for both cases.
        """
        return self._getResultValue('DurbinWatson', 'Durbin Watson p-value')


    def _getResultValue(self, test, description):
        """
        Generalized accessor method for the R2 or p-values.
        Parameters
        ----------
        test : string
            name of the keys for the dictionnary.
        description : string
            name the test to be displayed.
        """
        if self._censored:
            pValue = ot.NumericalPointWithDescription(
                        [(description + ' for uncensored case', 
                        self._resultsUnc.testResults[test]),
                        (description + ' for censored case',
                        self._resultsCens.testResults[test])])
        else:
            pValue = ot.NumericalPointWithDescription(
                        [(description + ' for uncensored case', 
                        self._resultsUnc.testResults[test])])
        return pValue