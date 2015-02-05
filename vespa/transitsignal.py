from __future__ import division, print_function

import numpy as np
import pandas as pd
import numpy.random as rand

import acor

from plotutils import setfig

from .transit_basic import traptransit, fit_traptransit, traptransit_MCMC
from .statutils import kdeconf, qstd, conf_interval

class TransitSignal(object):
    """a phased transit signal with the epoch of the transit at 0, and 'continuum' set at 1
    """
    def __init__(self,ts,fs,dfs=None,P=None,p0=None,name='',maxslope=None):

        ts = np.atleast_1d(ts)
        fs = np.atleast_1d(fs)

        inds = ts.argsort()
        self.ts = ts[inds]
        self.fs = fs[inds]
        self.name = name
        self.P = P

        if maxslope is None:
            maxslope = 30
        self.maxslope = maxslope
        if type(P) == type(np.array([1])):
            self.P = P[0]

        #set default best-guess trapezoid parameters
        if p0 is None:
            depth = 1 - fs.min()
            duration = (fs < (1-0.01*depth)).sum()/float(len(fs)) * (ts[-1] - ts[0])
            tc0 = ts[fs.argmin()]
            p0 = np.array([duration,depth,5.,tc0])

        tfit = fit_traptransit(ts,fs,p0)

        if dfs is None:
            dfs = (self.fs - traptransit(self.ts,tfit)).std()
        if np.size(dfs)==1:
            dfs = np.ones(len(self.ts))*dfs
        self.dfs = dfs

        self.dur,self.depth,self.slope,self.center = tfit
        self.trapfit = tfit

        logging.debug('trapezoidal leastsq fit: {}'.format(self.trapfit))

        self.hasMCMC=False

    def __eq__(self,other):
        return hash(self) == hash(other)

    def __hash__(self):
        key = 0
        key += hash(self.ts.__str__())
        key += hash(self.ts.sum())
        key += hash(self.fs.__str__())
        key += hash(self.fs.sum())
        key += hash(self.P)
        key += hash(self.maxslope)
        if self.hasMCMC:
            key += hash(self.slopes.sum())
            key += hash(str(self.slopes[:100]))
        return key
        
    def plot(self, fig=None, plot_trap=False, name=False, trap_color='g',
             trap_kwargs=None, **kwargs):

        setfig(fig)
        
        plt.plot(self.ts,self.fs,'.',**kwargs)

        if plot_trap and hasattr(self,'trapfit'):
            if trap_kwargs is None:
                trap_kwargs = {}
            plt.plot(self.ts, traptransit(self.ts,self.trapfit),
                     color=tt_color, **trap_kwargs)

        if name is not None:
            if type(name)==type(''):
                text = name
            else:
                text = self.name
            plt.annotate(text,xy=(0.1,0.1),xycoords='axes fraction',fontsize=22)

        if hasattr(self,'depthfit') and not np.isnan(self.depthfit[0]):
            lo = 1 - 3*self.depthfit[0]
            hi = 1 + 2*self.depthfit[0]
        else:
            lo = 1
            hi = 1

        sig = qstd(self.fs,0.005)
        hi = max(hi,self.fs.mean() + 7*sig)
        lo = min(lo,self.fs.mean() - 7*sig)
        logging.debug('lo={}, hi={}'.format(lo,hi))
        plt.ylim((lo,hi))
        plt.xlabel('time [days]')
        plt.ylabel('Relative flux')

    def MCMC(self, niter=500, nburn=200, nwalkers=200, threads=1,
             fit_partial=False, width=3, savedir=None, refit=False,
             thin=10, conf=0.95, maxslope=30, debug=False, p0=None):

        if fit_partial:
            wok = np.where((np.absolute(self.ts-self.center) < (width*self.dur)) &
                           ~np.isnan(self.fs))
        else:
            wok = np.where(~np.isnan(self.fs))

        alreadydone = True
        alreadydone &= savedir is not None
        alreadydone &= os.path.exists('%s/ts.npy' % savedir)
        alreadydone &= os.path.exists('%s/fs.npy' % savedir)

        if savedir is not None and alreadydone:
            ts_done = np.load('%s/ts.npy' % savedir)
            fs_done = np.load('%s/fs.npy' % savedir)
            alreadydone &= np.all(ts_done == self.ts[wok])
            alreadydone &= np.all(fs_done == self.fs[wok])
        
        if alreadydone and not refit:
            logging.info('MCMC fit already done for %s.  Loading chains.' % self.name)
            Ts = np.load('%s/duration_chain.npy' % savedir)
            ds = np.load('%s/depth_chain.npy' % savedir)
            slopes = np.load('%s/slope_chain.npy' % savedir)
            tcs = np.load('%s/tc_chain.npy' % savedir)
        else:
            logging.info('Fitting data to trapezoid shape with MCMC for %s....' % self.name)
            if p0 is None:
                p0 = self.trapfit.copy()
                p0[0] = np.absolute(p0[0])
                if p0[2] < 2:
                    p0[2] = 2.01
                if p0[1] < 0:
                    p0[1] = 1e-5
            logging.debug('p0 for MCMC = {}'.format(p0))
            sampler = tr.traptransit_MCMC(self.ts[wok],self.fs[wok],self.dfs[wok],
                                          niter=niter,nburn=nburn,nwalkers=nwalkers,
                                          threads=threads,p0=p0,return_sampler=True,
                                          maxslope=maxslope)

            Ts,ds,slopes,tcs = (sampler.flatchain[:,0],sampler.flatchain[:,1],
                                sampler.flatchain[:,2],sampler.flatchain[:,3])

            self.sampler = sampler
            if savedir is not None:
                np.save('%s/duration_chain.npy' % savedir,Ts)
                np.save('%s/depth_chain.npy' % savedir,ds)
                np.save('%s/slope_chain.npy' % savedir,slopes)
                np.save('%s/tc_chain.npy' % savedir,tcs)
                np.save('%s/ts.npy' % savedir,self.ts[wok])
                np.save('%s/fs.npy' % savedir,self.fs[wok])

        if debug:
            print(Ts)
            print(ds)
            print(slopes)
            print(tcs)

        N = len(Ts)
        self.Ts_acor = acor.acor(Ts)[1]
        self.ds_acor = acor.acor(ds)[1]
        self.slopes_acor = acor.acor(slopes)[1]
        self.tcs_acor = acor.acor(tcs)[1]
        self.fit_converged = True
        for t in [self.Ts_acor,self.ds_acor,
                  self.slopes_acor,self.tcs_acor]:
            if t > 0.1*N:
                self.fit_converged = False


        ok = (Ts > 0) & (ds > 0) & (slopes > 0) & (slopes < self.maxslope)
        logging.debug('trapezoidal fit has {} good sample points'.format(ok.sum()))
        if ok.sum()==0:
            if (Ts > 0).sum()==0:
                #logging.debug('{} points with Ts > 0'.format((Ts > 0).sum()))
                logging.debug('{}'.format(Ts))
                raise MCMCError('{}: 0 points with Ts > 0'.format(self.name))
            if (ds > 0).sum()==0:
                #logging.debug('{} points with ds > 0'.format((ds > 0).sum()))
                logging.debug('{}'.format(ds))
                raise MCMCError('{}: 0 points with ds > 0'.format(self.name))
            if (slopes > 0).sum()==0:
                #logging.debug('{} points with slopes > 0'.format((slopes > 0).sum()))
                logging.debug('{}'.format(slopes))
                raise MCMCError('{}: 0 points with slopes > 0'.format(self.name))
            if (slopes < self.maxslope).sum()==0:
                #logging.debug('{} points with slopes < maxslope ({})'.format((slopes < self.maxslope).sum(),self.maxslope))
                logging.debug('{}'.format(slopes))
                raise MCMCError('{} points with slopes < maxslope ({})'.format((slopes < self.maxslope).sum(),self.maxslope))


        durs,deps,logdeps,slopes,logslopes = (Ts[ok],ds[ok],np.log10(ds[ok]),
                                              slopes[ok],log10(slopes[ok]))
        
        
        inds = (np.arange(len(durs)/thin)*thin).astype(int)
        durs,deps,logdeps,slopes,logslopes = (durs[inds],deps[inds],logdeps[inds],
                                              slopes[inds],logslopes[inds])

        self.durs,self.logdeps,self.slopes = (durs,logdeps,slopes)

        self.durkde = gaussian_kde(durs)
        self.depthkde = gaussian_kde(deps)
        self.slopekde = gaussian_kde(slopes)
        self.logdepthkde = gaussian_kde(logdeps)


        if self.fit_converged:
            try:
                durconf = kdeconf(self.durkde,conf)
                depconf = kdeconf(self.depthkde,conf)
                logdepconf = kdeconf(self.logdepthkde,conf)
                slopeconf = kdeconf(self.slopekde,conf)
            except:
                raise
                raise MCMCError('Error generating confidence intervals...fit must not have worked.')

            durmed = np.median(durs)
            depmed = np.median(deps)
            logdepmed = np.median(logdeps)
            logslopemed = np.median(logslopes)
            slopemed = np.median(slopes)

            self.durfit = (durmed,array([durmed-durconf[0],durconf[1]-durmed]))
            self.depthfit = (depmed,array([depmed-depconf[0],depconf[1]-depmed]))
            self.logdepthfit = (logdepmed,array([logdepmed-logdepconf[0],logdepconf[1]-logdepmed]))
            self.slopefit = (slopemed,array([slopemed-slopeconf[0],slopeconf[1]-slopemed]))

        else:
            self.durfit = (np.nan,np.nan,np.nan)
            self.depthfit = (np.nan,np.nan,np.nan)
            self.logdepthfit = (np.nan,np.nan,np.nan)
            self.logslopefit = (np.nan,np.nan,np.nan)
            self.slopefit = (np.nan,np.nan,np.nan)


        points = array([durs,logdeps,slopes])
        self.kde = stats.gaussian_kde(points)

        self.hasMCMC = True

