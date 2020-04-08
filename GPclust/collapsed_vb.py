# Copyright (c) 2012, 2013, 2014 James Hensman
# Licensed under the GPL v3 (see LICENSE.txt)

import numpy as np
import GPy
import time
import sys #for flushing
from numpy.linalg.linalg import LinAlgError
class LinAlgWarning(Warning):
    pass

class CollapsedVB(GPy.core.Model):
    """
    A base class for collapsed variational models, using the GPy framework for
    non-variational parameters.

    Optimisation of the (collapsed) variational paremters is performed by
    Riemannian conjugate-gradient ascent, interleaved with optimisation of the
    non-variational parameters

    This class specifies a scheme for implementing the model, as well as
    providing the optimisation routine.
    """

    def __init__(self, name):
        """"""
        GPy.core.Model.__init__(self, name)

        self.hyperparam_interval=50

        self.default_method = 'HS'
        self.hyperparam_opt_args = {
                'max_iters': 20,
                'messages': 1,
                'clear_after_finish': True}

    def randomize(self):
        GPy.core.Model.randomize(self)
        self.set_vb_param(np.random.randn(self.get_vb_param().size))

    def get_vb_param(self):
        """Return a vector of variational parameters"""
        raise NotImplementedError

    def set_vb_param(self,x):
        """Expand a vector of variational parameters into the model"""
        raise NotImplementedError

    def bound(self):
        """Returns the lower bound on the marginal likelihood"""
        raise NotImplementedError

    def vb_grad_natgrad(self):
        """Returns the gradient and natural gradient of the variational parameters"""

    def log_likelihood(self):
        """
        In optimising the non variational (e.g. kernel) parameters, use the
        bound as a proxy for the likelihood
        """
        return self.bound()

    def optimize(self, method='HS', maxiter=500, ftol=1e-6, gtol=1e-6, step_length=1., callback=None, verbose=True):
        """
        Optimize the model.

        The strategy is to run conjugate natural gradients on the variational
        parameters, interleaved with gradient based optimization of any
        non-variational parameters. self.hyperparam_interval dictates how
        often this happens.

        Arguments
        ---------
        :method: ['FR', 'PR','HS','steepest'] -- conjugate gradient method
        :maxiter: int
        :ftol: float
        :gtol: float
        :step_length: float

        """

        assert method in ['FR', 'PR','HS','steepest'], 'invalid conjugate gradient method specified.'

        ## For GPy style notebook verbosity

        if verbose:
            try:
                from IPython.display import display
                from IPython.html.widgets import IntProgress, HTML, Box, VBox, HBox, FlexBox
                self.text = HTML(width='100%')
                self.progress = IntProgress(min=0, max=maxiter)
                self.progress.bar_style = 'info'
                self.status = 'Running'

                html_begin = """<style type="text/css">
                .tg-opt  {font-family:"Courier New", Courier, monospace !important;padding:2px 3px;word-break:normal;border-collapse:collapse;border-spacing:0;border-color:#DCDCDC;margin:0px auto;width:100%;}
                .tg-opt td{font-family:"Courier New", Courier, monospace !important;font-weight:bold;color:#444;background-color:#F7FDFA;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#DCDCDC;}
                .tg-opt th{font-family:"Courier New", Courier, monospace !important;font-weight:normal;color:#fff;background-color:#26ADE4;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#DCDCDC;}
                .tg-opt .tg-left{font-family:"Courier New", Courier, monospace !important;font-weight:normal;text-align:left;}
                .tg-opt .tg-right{font-family:"Courier New", Courier, monospace !important;font-weight:normal;text-align:right;}
                </style>
                <table class="tg-opt">"""

                html_end = "</table>"

                self.ipython_notebook = True
            except:
                # Not in Ipython notebook
                self.ipython_notebook = False
        else:
            self.ipython_notebook = False

        if self.ipython_notebook:
            left_col = VBox(children=[self.progress, self.text], padding=2, width='100%')
            self.hor_align = FlexBox(children = [left_col], width='100%', orientation='horizontal')

            display(self.hor_align)

            try:
                self.text.set_css('width', '100%')
                left_col.set_css({
                         'padding': '2px',
                         'width': "100%",
                         })

                self.hor_align.set_css({
                         'width': "100%",
                         })

                self.hor_align.remove_class('vbox')
                self.hor_align.add_class('hbox')

                left_col.add_class("box-flex1")

            except:
                pass

        self.start = time.time()
        self._time = self.start

        ## ---

        iteration = 0
        bound_old = self.bound()
        searchDir_old = 0.
        iteration_failed = False
        while True:

            if callback is not None:
                callback()

            grad,natgrad = self.vb_grad_natgrad()
            grad,natgrad = -grad,-natgrad
            squareNorm = np.dot(natgrad,grad) # used to monitor convergence

            #find search direction
            if (method=='steepest') or not iteration:
                beta = 0
            elif (method=='PR'):
                beta = np.dot((natgrad-natgrad_old),grad)/squareNorm_old
            elif (method=='FR'):
                beta = squareNorm/squareNorm_old
            elif (method=='HS'):
                beta = np.dot((natgrad-natgrad_old),grad)/np.dot((natgrad-natgrad_old),grad_old)
            if np.isnan(beta) or (beta < 0.):
                beta = 0.
            searchDir = -natgrad + beta*searchDir_old

            # Try a conjugate step
            phi_old = self.get_vb_param().copy()
            try:
                self.set_vb_param(phi_old + step_length*searchDir)
                bound = self.bound()
            except LinAlgError:
                self.set_vb_param(phi_old)
                bound = bound_old-1

            iteration += 1

            # Make sure there's an increase in the bound, else revert to steepest, which is guaranteed to increase the bound.
            # (It's the same as VBEM.)
            if bound < bound_old:
                searchDir = -natgrad
                try:
                    self.set_vb_param(phi_old + step_length*searchDir)
                    bound = self.bound()
                except LinAlgError:
                    import warnings
                    warnings.warn("Caught LinalgError in setting variational parameters, trying to continue with old parameter settings", LinAlgWarning)
                    self.set_vb_param(phi_old)
                    bound = self.bound()
                    iteration_failed = False
                iteration += 1


            if verbose:
                if self.ipython_notebook:

                    t = time.time()
                    seconds = t-self.start

                    self.status = 'Running'
                    self.progress.bar_style = 'info'

                    names_vals = [['conjugate gradient method', "{:s}".format(method)],
                                  ['runtime', "{:.1f}s".format(seconds)],
                                  ['evaluation', "{}".format(iteration)],
                                  ['objective', "{:12.5f}".format(-bound)],
                                  ['||gradient||', "{:12.5f}".format(float(squareNorm))],
                                  ['beta', "{:12.5f}".format(beta)],
                                  ['status', "{:s}".format(self.status)],
                                ]

                    html_body = ""
                    for name, val in names_vals:
                        html_body += "<tr>"
                        html_body += "<td class='tg-left'>{}</td>".format(name)
                        html_body += "<td class='tg-right'>{}</td>".format(val)
                        html_body += "</tr>"

                    self.progress.value = iteration
                    self.text.value = html_begin + html_body + html_end

                else:
                    print('\riteration '+str(iteration)+' bound='+str(bound) + ' grad='+str(squareNorm) + ', beta='+str(beta))
                    sys.stdout.flush()

            # Converged yet? try the parameters if so
            if np.abs(bound-bound_old) <= ftol:
                if verbose:
                    if self.ipython_notebook:
                        self.status = 'vb converged (ftol)'
                        names_vals[-1] = ['status', "{:s}".format(self.status)]

                        html_body = ""
                        for name, val in names_vals:
                            html_body += "<tr>"
                            html_body += "<td class='tg-left'>{}</td>".format(name)
                            html_body += "<td class='tg-right'>{}</td>".format(val)
                            html_body += "</tr>"

                        self.text.value = html_begin + html_body + html_end
                        self.progress.bar_style = 'success'

                    else:
                        print('vb converged (ftol)')

                if self.optimize_parameters() < 1e-1:
                    break

            if squareNorm <= gtol:
                if verbose:
                    if self.ipython_notebook:
                        self.status = 'vb converged (gtol)'
                        names_vals[-1] = ['status', "{:s}".format(self.status)]

                        html_body = ""
                        for name, val in names_vals:
                            html_body += "<tr>"
                            html_body += "<td class='tg-left'>{}</td>".format(name)
                            html_body += "<td class='tg-right'>{}</td>".format(val)
                            html_body += "</tr>"

                        self.text.value = html_begin + html_body + html_end
                        self.progress.bar_style = 'success'

                    else:
                        print('vb converged (gtol)')

                if self.optimize_parameters() < 1e-1:
                    break

            if iteration >= maxiter:
                if verbose:
                    if self.ipython_notebook:
                        self.status = 'maxiter exceeded'
                        names_vals[-1] = ['status', "{:s}".format(self.status)]

                        html_body = ""
                        for name, val in names_vals:
                            html_body += "<tr>"
                            html_body += "<td class='tg-left'>{}</td>".format(name)
                            html_body += "<td class='tg-right'>{}</td>".format(val)
                            html_body += "</tr>"

                        self.text.value = html_begin + html_body + html_end
                        self.progress.bar_style = 'warning'

                    else:
                        print('maxiter exceeded')
                break

            #store essentials of previous iteration
            natgrad_old = natgrad.copy() # copy: better safe than sorry.
            grad_old = grad.copy()
            searchDir_old = searchDir.copy()
            squareNorm_old = squareNorm

            # hyper param_optimisation
            if ((iteration >1) and not (iteration%self.hyperparam_interval)) or iteration_failed:
                self.optimize_parameters()

            bound_old = bound

        # Clean up temporary fields after optimization
        if self.ipython_notebook:
            del self.text
            del self.progress
            del self.hor_align



    def optimize_parameters(self):
        """
        Optimises the model parameters (non variational parameters)
        Returns the increment in the bound acheived
        """
        if self.optimizer_array.size>0:
            start = self.bound()
            GPy.core.model.Model.optimize(self,**self.hyperparam_opt_args)
            return self.bound()-start
        else:
            return 0.
