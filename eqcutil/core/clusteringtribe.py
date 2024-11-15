"""
:module: eqcutil.core.clusteringtribe.ClusteringTribe
:auth: Nathan T. Stevens
:email: ntsteven@uw.edu
:org: Pacific Northwest Seismic Network
:license: GNU GPLv3
:purpose: This contains a child-class of the :class:`~eqcorrscan.Tribe` class
    and provides extended functionalities for template clustering methods
    as class-methods.
:attribution: This builds on the EQcorrscan project. If you find this class
    useful please be sure to cite both EQcorrscan (e.g., Chamberlain et al., 2017)
    and perhaps this repository as well.

    TODO: provide an option to just save the paths to the source templates
    TODO: change `self.clusters` to `self.index`
"""
import os, logging, tarfile, shutil, pickle, tempfile, glob, fnmatch

from copy import deepcopy
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform
from obspy import read_events, read
from obspy.core.event import Catalog
from eqcorrscan import Tribe, Template

import eqcorrscan.utils.clustering as euc
from eqcorrscan.core.match_filter.helpers import _safemembers, _par_read

from eqcutil.viz import eqc_compat

Logger = logging.getLogger(__name__)

class ClusteringTribe(Tribe):
    """An augmentation of the :class:`~eqcorrscan.Tribe` class that
    extends EQcorrscan Tribe clustering and stacking methods as 
    class-methods. This method also includes a method for de-duplicating
    input template names prior to adding them to the **templates** attribute

    Parameters
    ----------
    :param templates: (list of) :class:`~eqcorrscan.Template` objects, defaults to []
    :type templates: list or :class:`~eqcorrscan.Template, optional

    Attributes
    ----------
    :var templates: list of eqcorrscan.Template objects
    :var clusters: pandas.DataFrame of template membership in one or
        more clustering analysis.
    :var cluster_kwargs: dictionary that preserves key-word arguments
        input to the :meth:`~.ClusteringTribe.cluster` method, keyed
        by the **method** selected
    :var dist_mat: :class:`~pandas.DataFrame` object that saves the distance
        matrix generated by cross-correlation clustering between templates.
        Columns and Index values are template names
    """    
    def __init__(self, templates=[]):
        """Initialize a ClusteringTribe object

        :param templates: _description_, defaults to []
        :type templates: list, optional
        """
        super().__init__()
        # If eqc_compat.plant() has not been run, do it now      
        if not hasattr(self,'snuffle'):
            eqc_compat.plant()

        self.clusters = pd.DataFrame(columns=['id_no'])
        self.dist_mat = None
        self.cluster_kwargs = {}

        if isinstance(templates, Template):
            templates = [templates]
        elif isinstance(templates, list):
            if all(isinstance(_t, Template) for _t in templates):
                pass
            else:
                raise TypeError
        
        for template in templates:
            self.extend(template)

    def extend(self, other, **options):
        """Extend this ClusteringTribe with more :class:`~eqcorrscan.Template`
        objects.

        Options are fed to :meth:`~.ClusteringTribe.add_template` which provides
        default support for re-naming incoming templates in **other** that have
        duplicate names of templates already in this ClusteringTribe

        :param other: a single or iterable collection of templates
        :type other: eqcorrscan.Template or iterable collection thereof (e.g. eqcorrscan.Tribe)
        """        
        if isinstance(other, Template):
            self.add_template(other,**options)
        elif isinstance(other, Tribe):
            for template in other:
                self.add_template(template,**options)
        elif hasattr(other, '__iter__'):
            if all(isinstance(_e, Template) for _e in other):
                for tempate in other:
                    self.add_template(template,**options)
        else:
            Logger.warning(f'type of other does not conform with ClusteringTribe.extend')

    def _deduplicate_name(self, other, delimiter='__', start=0):
        if other not in self.clusters.index.values:
            return other
        else:
            if delimiter not in other:
                basename = other
            else:
                basename = other.split('__')[0]
            matches = fnmatch.filter(self.clusters.index.values, basename+'*')
            while f'{basename}{delimiter}{start}' in matches:
                start += 1
            return f'{basename}{delimiter}{start}'

    def add_template(self, other, rename_duplicates=False, **options):
        if isinstance(other, Template):
            if other.name in self.clusters.index.values:
                if rename_duplicates:
                    other.name = self._deduplicate_name(other.name, **options)
                else:
                    raise AttributeError(f'duplicate name {other.name} - aborting add_template')
            self.templates.append(other)
            self.clusters = pd.concat([self.clusters, pd.DataFrame({'id_no':len(self)-1}, index=[other.name])],
                                      axis=0, ignore_index=False)
        else:
            raise TypeError('other must be type eqcorrscan.Template')

    def _get_template_list(self, use_name=False):
        """Create a template_list input for 
        :meth:`~eqcorrscan.utils.clusering.cluster`
        from this ClusteringTribe with the option
        to use template names instead of position
        values.

        :return: _description_
        :rtype: _type_
        """
        if use_name:
            return [(_t.st, _t.name) for _t in self]      
        else:       
            return [(_t.st, _e) for _e, _t in enumerate(self)]

    def cluster(self, method, **kwargs):
        """Extended wrapper for EQcorrscan Template correlation methods
        In addition to the original options of clustering using catalog
        methods (space_cluster and (space_time_cluster) this method now
        also permits use of :meth:`~eqcorrscan.util.clustering.cluster`
        under the method name `correlation_cluster`. Groups are saved
        to the **clusters** and **cluster_kwargs** attributes, which are
        dictionaries keyed by 

        :param method: _description_
        :type method: _type_
        """
        if len(self) < 2:
            raise AttributeError('insufficient number of templates to cluster') 

        index = []; values = []

        if method in ['space_cluster','space_time_cluster']:
            tribes = Tribe.cluster(self, method, **kwargs)
            for _e, tribe in enumerate(tribes):
                for template in tribe:
                    index.append(template.name)
                    values.append(_e)

        elif method == 'correlation_cluster':
            if 'save_corrmat' in kwargs.keys():
                if not kwargs['save_corrmat']:
                    save_local = False
                    kwargs['save_corrmat'] = True
                else:
                    save_local = True
            else:
                kwargs.update({'save_corrmat': True})
                save_local = False

            groups = euc.cluster(self._get_template_list(), **kwargs)
            if 'save_corrmat' in kwargs.keys():
                self.dist_mat = np.load('dist_mat.npy')
                if not save_local:
                    os.remove('dist_mat.npy')
            for _e, group in enumerate(groups):
                for entry in group:
                    index.append(self.templates[entry[1]].name)
                    values.append(_e)
        else:
            raise ValueError(f'method {method} not supported.')

        self.cluster_kwargs.update({method: kwargs})
        if self.clusters is None:
            self.clusters = pd.DataFrame(data=values,columns=[method], index=index)
        elif method not in self.clusters.columns:
            self.clusters = pd.concat([self.clusters, pd.DataFrame({method: values}, index=index)],
                                      axis=1, ignore_index=False)
        else:
            for _e, name in enumerate(index):
                self.clusters.loc[name, method] = values[_e]

    def get_subset(self, names):
        """Get an arbitrary subset of templates based on a list
        of template names. This will also create a subset view
        of the **clusters**, **cluster_kwargs**, and **dist_mat**
        attributes in the output **subset**

        :param names: name or list of names of templates to select
        :type names: str or list-like thereof
        :return:
         - **subset** (:class:`~.ClusteringTribe`) -- subset view
            of templates based on the provided list of template names
        """   
        # Catch single name entry
        if isinstance(names, str):
            names = [names]
        # Catch case where not all names are present
        if not set(names) <= set(self.clusters.index.values):
            raise ValueError('Not all provided names match templates in this ClusterTribe')
        # Proceed with making subset
        subset = self.__class__(templates = [self.select(name) for name in names])
        # Subset the clusters index
        subset.clusters = self.clusters[self.clusters.index.isin(names)]
        subset.cluster_kwargs = self.cluster_kwargs
        # If there is a dist_mat, also subset that
        if self.dist_mat is not None:
            subset.dist_mat = np.full(shape=(len(names), len(names)), fill_value=np.nan)
            for xx,ii in enumerate(subset.clusters.id_no.values):
                for yy,jj in enumerate(subset.clusters.id_no.values):
                    subset.dist_mat[xx,yy] = self.dist_mat[ii,jj]
        # return subset
        return subset

    def select_cluster(self, method, index):
        """Return a subset view of this ClusteringTribe for a specific
        clustering method and cluster index number

        uses the :meth:`~.ClusteringTribe.get_subset` method

        :param method: clustering method name
        :type method: str
        :param index: cluster index  number
        :type index: int
        :return: 
         - **subset** (:class:`~.ClusteringTribe`) -- subset view
         of this ClusteringTribe's contents for the specified method
         and index number
        """        
        if self.clusters is None:
            return 
        elif method not in self.clusters.columns:
            Logger.warning(f'cluster method {method} not yet run on this ClusteringTribe')
        names = self.clusters[self.clusters[method] == index].index.values
        return self.get_subset(names)


    def _get_template_list(self):
        """Produce a template_list input for :meth:`~eqcorrscan.utils.clustering.cluster`
        from the contents of this :class:`~.ClusteringTribe`

        :return: 
         - **tl** (*list*) - list of tuples (st, id_no) from each template
        """        
        tl = [(self.select(name).st, row.id_no) for name, row in self.clusters.iterrows()]
        return tl


    def _get_linkage(self, **kwargs):
        """Perform hierarchical/agglomerative clustering on the templates in this
        Cluster

        :return:
         - **Z** (*numpy.ndarray*) -- linkage matrix
        """        
        if 'correlation_cluster' not in self.clusters.columns:
            Logger.critical(f'correlation clustering has not been run on this ClusteringTribe')
        else:
            ckw = self.cluster_kwargs['correlation_cluster']
        if self.dist_mat is None:
            Logger.critical('dist_mat not populated')
        else:
            # Get linkage inputs
            rndw = ckw['replace_nan_distances_with']
            for _k, _v in [('method','single'), ('metric', 'euclidian'), ('optimal_ordering', False)]:
                if _k in ckw.keys() and _k not in kwargs.keys():
                    kwargs.update({_k: ckw[_k]})
                else:
                    kwargs.update({_k: _v})

            dm = self.dist_mat
            # Apply fill
            dist_mat = euc.handle_distmat_nans(dm, rndw)
            # Vectorize
            dist_vect = squareform(dist_mat)
            # Recalculate linkage
            Z = linkage(dist_vect, **kwargs)
            return Z

    def _cct_regroup(self, corr_thresh, **kwargs):
        """Regroup cross-correlated templates at a different correlation
        threshold with options to re-define the linkage parameterization
    
        :param corr_thresh: template cross correlation threshold for grouping,
            must be a value in 0 < corr_thresh < 1
        :type corr_thresh: float
        :return: _description_
        :rtype: _type_
        """        
        if 'correlation_cluster' not in self.clusters.columns:
            Logger.critical(f'correlation clustering has not been run on this ClusteringTribe')
        else:
            ckw = self.cluster_kwargs['correlation_cluster']

        Z = self._get_linkage(**kwargs)

        if not isinstance(corr_thresh, float):
            Logger.critical(f'corr_thresh must be type float')
        elif not 0 < corr_thresh <= 1:
            Logger.critical(f'corr_thresh must be in (0, 1)')
        
        if corr_thresh == ckw['corr_thresh']:
            Logger.info(f'Already grouped for corr_thresh={corr_thresh}')
            return self.clusters['correlation_cluster']
        else:
            # Get new grouping
            indices = euc.fcluster(Z, t= 1 - corr_thresh, criterion='distance')
        
            output = pd.Series(data=indices, index=self.clusters.index, name='correlation_cluster')
            return output
        
    def dendrogram(self, xlabelfield='id_no', corr_thresh=None, **kwargs):
        """Wrapper for :meth:`~scipy.cluster.hierarchy.dendrogram` that uses
        saved attribute values from a running :meth:`~.ClusteringTribe.cluster`
        with method='correlation_cluster' to produce a dendrogram plot

        :param corr_thresh: correlation threshold to use for defining clusters,
            displayed cutoffs are defaults to None
        :type corr_thresh: _type_, optional
        :return: _description_
        :rtype: _type_
        """        
        if 'correlation_cluster' not in self.clusters.columns:
            Logger.critical(f'correlation clustering has not been run on this ClusteringTribe')
        
        lkwargs = {}
        for _k, _v in kwargs.items():
            if _k in ['method','metric','optimal_ordering']:
                lkwargs.update({_k, kwargs.pop(_k)})

        Z = self._get_linkage(**lkwargs)
        if corr_thresh is None:
            threshold = 1 - self.cluster_kwargs['correlation_cluster']['corr_thresh']
        else:
            threshold = 1 - corr_thresh

        if 'ax' not in kwargs.keys():
            fig = plt.figure()
            ax = fig.add_subplot(111)
            kwargs.update({'ax': ax})
        else:
            ax = kwargs['ax']
        
        if xlabelfield in self.clusters.columns:
            xlvalues = self.clusters[xlabelfield].values
            
        elif xlabelfield == 'index':
            xlvalues = self.clusters.index.values
        else:
            xlvalues = None

        kwargs.update({'color_threshold': threshold})
        if 'distance_sort' not in kwargs.keys():
            kwargs.update({'distance_sort': 'ascending'})

        if 'title' in kwargs.keys():
            title = kwargs.pop('title')
        else:
            title = ''

        R = dendrogram(Z, **kwargs)

        if not xlvalues is None:
            newlabels = []
            for _txt in ax.get_xticklabels():
                ind = int(_txt.get_text())
                newlabel = xlvalues[ind]
                newlabels.append(newlabel)
            ax.set_xticklabels(newlabels)
            ax.set_xlabel(xlabelfield)
        else:
            ax.set_xlabel('Entry Number')
        ax.set_ylabel('Linkage Distance\n[1 - corr]')
        ckw = self.cluster_kwargs['correlation_cluster']


        

        title += f'Fill Value: {ckw["replace_nan_distances_with"]} | '
        title += f'Corr Thresh: {1 - threshold} | Shift Length: {ckw["shift_len"]} sec'
        ax.set_title(title)
        return R





    def write(self, filename, compress=True, catalog_format="QUAKEML"):
        """
        Write the clusteringtribe to a file using tar archive formatting.

        :type filename: str
        :param filename:
            Filename to write to, if it exists it will be appended to.
        :type compress: bool
        :param compress:
            Whether to compress the tar archive or not, if False then will
            just be files in a folder.
        :type catalog_format: str
        :param catalog_format:
            What format to write the detection-catalog with. Only Nordic,
            SC3ML, QUAKEML are supported. Note that not all information is
            written for all formats (QUAKEML is the most complete, but is
            slow for IO).

        .. rubric:: Example

        >>> tribe = ClusteringTribe(templates=[Template(name='c', st=read())])
        >>> tribe.write('test_tribe')
        Tribe of 1 templates
        >>> tribe.write(
        ...    "this_wont_work.bob",
        ...    catalog_format="BOB") # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        TypeError: BOB is not supported
        """
        from eqcorrscan.core.match_filter import CAT_EXT_MAP

        if catalog_format not in CAT_EXT_MAP.keys():
            raise TypeError("{0} is not supported".format(catalog_format))
        dirname, ext = os.path.splitext(filename)

        # Make directory if it doesn't exist
        if not os.path.isdir(dirname):
            os.makedirs(dirname)
        self._par_write(dirname)

        # Compose tribe catalog
        tribe_cat = Catalog()
        for t in self.templates:
            if t.event is not None:
                # Check that the name in the comment matches the template name
                for comment in t.event.comments:
                    if not comment.text:
                        comment.text = "eqcorrscan_template_{0}".format(t.name)
                    elif comment.text.startswith("eqcorrscan_template_"):
                        comment.text = "eqcorrscan_template_{0}".format(t.name)
                tribe_cat.append(t.event)

        # Write catalog to disk
        if len(tribe_cat) > 0:
            tribe_cat.write(
                os.path.join(dirname, 'tribe_cat.{0}'.format(
                    CAT_EXT_MAP[catalog_format])), format=catalog_format)
            
        # Write template streams to disk
        for template in self.templates:
            template.st.write(
                os.path.join(dirname, '{0}.ms'.format(template.name)),
                format='MSEED')
        # ADDED BY NTS - write clustering summary to disk
        self.clusters.to_csv(os.path.join(dirname,'clusters.csv'), header=True, index=True)

        # Write clustering kwargs to disk
        for _k, _v in self.cluster_kwargs.items():
            with open(os.path.join(dirname, f'{_k}_kwargs.csv'), 'w') as file:
                for _l, _w in _v.items():
                    if isinstance(_w, str):
                        file.write(f'{_l},{_w}\n')
                    else:
                        file.write(f'{_l},{repr(_w)}\n')
        if self.dist_mat is not None:
            np.save(os.path.join(dirname,'dist_mat.npy'), np.array(self.dist_mat))

        # Run compression if specified
        if compress:
            if not filename.endswith(".tgz"):
                Logger.info("Appending '.tgz' to filename.")
                filename += ".tgz"
            with tarfile.open(filename, "w:gz") as tar:
                tar.add(dirname, arcname=os.path.basename(dirname))
            shutil.rmtree(dirname)
        return self

    def read(self, filename):
        """
        Read a clustertribe of templates from a tar formatted file.

        :type filename: str
        :param filename: File to read templates from.

        .. rubric:: Example

        >>> tribe = Tribe(templates=[Template(name='c', st=read())])
        >>> tribe.write('test_tribe')
        Tribe of 1 templates
        >>> tribe_back = Tribe().read('test_tribe.tgz')
        >>> tribe_back == tribe
        True
        >>> # This can also read pickled templates
        >>> import pickle
        >>> with open("test_tribe.pkl", "wb") as f:
        ...    pickle.dump(tribe, f)
        >>> tribe_back = Tribe().read("test_tribe.pkl")
        >>> tribe_back == tribe
        True
        """
        if filename.endswith(".pkl"):
            with open(filename, "rb") as f:
                self.__iadd__(pickle.load(f))
            return self
        with tarfile.open(filename, "r:*") as arc:
            temp_dir = tempfile.mkdtemp()
            arc.extractall(path=temp_dir, members=_safemembers(arc))
            tribe_dir = glob.glob(temp_dir + os.sep + '*')[0]
            self._read_from_folder(dirname=tribe_dir)
        shutil.rmtree(temp_dir)
        # Assign unique ids
        # self.__unique_ids()
        return self

    def _read_from_folder(self, dirname):
        """
        Internal folder reader.

        :type dirname: str
        :param dirname: Folder to read from.
        """
        templates = _par_read(dirname=dirname, compressed=False)
        # Template Waveform Files
        t_files = glob.glob(dirname + os.sep + '*.ms')
        # Catalog Files
        tribe_cat_file = glob.glob(os.path.join(dirname, "tribe_cat.*"))
        # NEW - cluster summary file
        cluster_file = glob.glob(os.path.join(dirname,'clusters.csv'))
        # NEW - clustering kwargs file
        cluster_kwarg_files = glob.glob(os.path.join(dirname,'*_kwargs.csv'))
        # NEW - distance matrix file
        dist_mat_file = glob.glob(os.path.join(dirname, 'dist_mat.npy'))
        # Load catalog if it is present
        if len(tribe_cat_file) != 0:
            tribe_cat = read_events(tribe_cat_file[0])
        else:
            tribe_cat = Catalog()

        # Load templates with new names
        previous_template_names = [t.name for t in self.templates]
        for template in templates:
            if template.name in previous_template_names:
                # Don't read in for templates that we already have.
                continue
            for event in tribe_cat:
                for comment in event.comments:
                    if comment.text == 'eqcorrscan_template_' + template.name:
                        template.event = event
            t_file = [t for t in t_files
                      if t.split(os.sep)[-1] == template.name + '.ms']
            if len(t_file) == 0:
                Logger.error('No waveform for template: ' + template.name)
                continue
            elif len(t_file) > 1:
                Logger.warning('Multiple waveforms found, using: ' + t_file[0])
            template.st = read(t_file[0])
        # Remove templates that do not have streams
        templates = [t for t in templates if t.st is not None]
        self.templates.extend(templates)

        # Re-constitute groups
        if len(cluster_file) != 0:
            clusters = pd.read_csv(cluster_file[0], index_col=[0])
        else:
            clusters = pd.DataFrame()

        # Remove lines that don't match loaded templates
        if len(clusters) != 0:
            clusters = clusters[clusters.index.isin([_t.name for _t in templates])]

            if set(clusters.index.values) == {_t.name for _t in templates}:
                if self.clusters is None:
                    self.clusters = clusters
                else:
                    self.clusters = pd.concat([self.clusters, clusters], axis=0, ignore_index=False)
            else:
                Logger.error('cluster_group file names loaded do not match template names loaded')

        # Reconstitute processing information
        for ckf in cluster_kwarg_files:
            path, name = os.path.split(ckf)
            name, ext = os.path.splitext(name)
            ctype = name[:-7]
            self.cluster_kwargs.update({ctype: {}})
            df = pd.read_csv(ckf, index_col=[0], header=None)
            for _k, _r in df.iterrows():
                _r = _r.values[0]
                if _r == 'True':
                    _r = True
                elif _r == 'False':
                    _r = False
                else:
                    try:
                        float(_r)
                        _r = float(_r)
                    except ValueError:
                        pass
                self.cluster_kwargs[ctype].update({_k: _r})

                # try:
                #     self.cluster_kwargs[ctype].update({_k: float(_r.values[0])})
                # except ValueError:
                #     self.cluster_kwargs[ctype].update({_k: _r.values[0]})
                
        # Load dist_mat
        if len(dist_mat_file) > 0:
            dist_mat = np.load(dist_mat_file[0])
            self.dist_mat = dist_mat
        return

    def select_template_traces(self, remove_empty_templates=True, **kwargs):
        """Use the :meth:`~obspy.core.stream.Stream.select` to subsample the
        streams attached to each :class:`~eqcorrscan.Template` in this :class:`~.ClusteringTribe`

        Provides the option to get rid of empty templates

        NOTE: This method applies in-place changes to template and stream
        objects in this ClusteringTribe. If you want to save your data, use
        the :meth:`~.ClusteringTribe.copy` method to create a duplicate
        before running this method.

        :param remove_empty_templates: should empty templates be removed from this Tribe?
            Defaults to True
        :type remove_empty_templates: bool, optional
        :param kwargs: key-word argument collector that passes kwargs to 
            :meth:`~obspy.core.stream.Stream.select`
        """        
        # Iterate across templates
        for template in self:
            # Use obspy.core.stream.Stream.select to subset trace
            template.st = template.st.select(**kwargs)
            # Assess if template waveforms is empty & if we want to remove empties
            if len(template.st) == 0 and remove_empty_templates:
                # If so, remove using eqcorrscan.Tribe.remove
                self.remove(template)


    def copy(self):
        return deepcopy(self)


    def remove(self, template):
        """Remove a specified template from this ClusteringTribe

        removes both the template and it's entry from the **clusters** attribute

        :param template: _description_
        :type template: _type_
        """        
        if template in self.templates:
            # remove the template entry from self.clusters
            self.clusters.drop(labels=template.name)
            # remove the template
            Tribe.remove(self, template)

    # # def get_summary(self):
    # #     """Return a summary of the clustering membership of
    # #     each template in this ClusteringTribe. Columns are
    # #     clustering method names, Index values are template names
    # #     integer values are the 

    # #     :return: _description_
    # #     :rtype: _type_
    # #     """        
    # #     index = [_t.name for _t in self]
    # #     columns = list(self.clusters.key())
    # #     if len(columns) > 0:
    # #         data = np.full(shape=(len(index), len(columns)), fill_value=np.nan)
    # #     df = pd.DataFrame(data=data, index=index, columns=columns)
    # #     # Iterate over cluster type
    # #     for ctype, cgroups in self.clusters.items():
    # #         # Iterate over subtribe number and subtribe
    # #         for _stn, tribe in cgroups.items():
    # #             # Iterate over template in tribe
    # #             for template in tribe:
    # #                 # Write subgroup number to name,cluster_type position
    # #                 df.loc[template.name, ctype] = _stn
    # #     return df

    # # summary = property(get_summary)


    
    # template_list = property(get_template_list)

    # def extend(self, other, **options):
    #     Tribe.extend(self, other, **options)
    #     new_lines = 



    


    # def corr_cluster(self, savedir='cluster_results', show=False, corr_thresh=0.3,
    #             shift_len=1., allow_individual_trace_shifts=False, dist_nan_fill=None,
    #            cores='all', method='linear', metric='euclidian',
    #            optimal_ordering=False, save_subtribes=False):
    #     """Wraps the :meth:`~eqcorrscan.util.clustering.cluster` method and 
    #     added saving and formatting functionalities provided by the eqcorrscan_utils
    #     package. 

    #     :param savedir: where clustering results are saved, defaults to 'cluster_results'
    #     :type savedir: str, optional
    #     :param show: should the sub-call of `cluster` display the groups as a dendrogram? Defaults to False
    #     :type show: bool, optional
    #     :param corr_thresh: correlation threshold for grouping, defaults to 0.3
    #     :type corr_thresh: float, optional
    #     :param shift_len: number of seconds templates are allowed to be shifted
    #         durring cross correlations, defaults to 1.
    #     :type shift_len: float, optional
    #     :param allow_individual_trace_shifts: allow each trace in a template to be
    #         shifted during cross correlations? Defaults to False
    #     :type allow_individual_trace_shifts: bool, optional
    #     :param dist_nan_fill: fill value for NaN entries in the distance matrix
    #         calculated by `cluster` (its replace_nan_distances_with arg),
    #         defaults to None.
    #         Supported Values:
    #          - 'mean'
    #          - 'min'
    #          - [0, 1]
    #          also see :meth:`~eqcorrscan.utils.clustering.cluster`
    #     :type dist_nan_fill: str, float, or NoneType, optional
    #     :param cores: number of cores to use for `cluster`, defaults to 'all'
    #     :type cores: str, optional
    #     :param method: linkage method, defaults to 'linear'
    #         also see :meth:`~scipy.clustering.hierarchy.linkage
    #     :type method: str, optional
    #     :param metric: linkage metric, defaults to 'euclidian'
    #     :type metric: str, optional
    #     :param optimal_ordering: linkage optimal_ordering, defaults to False
    #     :type optimal_ordering: bool, optional
    #     :param save_subtribes: should subtribes be saved in savedir?, defaults to False
    #     :type save_subtribes: bool, optional
    #     """



    #     # Create Template List
    #     template_list = [(_t.st, _e) for _e, _t in enumerate(self)]
    #     # Run Clustering
    #     groups = euc.cluster(
    #         template_list,
    #         show=show,
    #         corr_thresh=corr_thresh,
    #         shift_len=shift_len,
    #         allow_individual_trace_shifts=allow_individual_trace_shifts,
    #         replace_nan_distances_with=dist_nan_fill,
    #         cores=cores,
    #         method=method,
    #         metric=metric,
    #         optimal_ordering=optimal_ordering)
    #     # Populate/re-initialize subtribes
    #     self.clusters = {}
    #     if savedir:
    #         subtribes = save_cluster_results(self, groups, savedir=savedir, save_subtribes=save_subtribes)
    #         for _k, _v in subtribes.items():
    #             self.clusters.update({_k, self.__class__(templates=_v)})
    #     else:
    #         for _e, group in groups:
    #             self.clusters.update({_e: self.__class__()})
    #             for entry in group:
    #                 self.clusters[_e] += self.templates[entry[1]]
    #     # Load the distance matrix into this 
    #     self.dist_mat = np.load(Path().cwd() / 'dist_mat.npy')
    #     self.clustering_threshold=corr_thresh
    #     self.dist_nan_fill = dist_nan_fill
    #     self.savedir = savedir
    

    # def write(self, savedir):
    #     if self.groups is None:
    #         Tribe.write(self, savedir, 'templates.tgz')
    #     gfile = os.path.join(savedir, 'groups.csv')
        


    # def load(self, loaddir):
    #     gfile = os.path.join(loaddir, 'groups.csv')
    #     pfile = os.path.join()
    #     if not os.path.isfile(os.path.join(loaddir,'groups.csv')):
    #         Logger.critical(f'could not find groups.csv in {loaddir}')
    #     else:
    #         with open()
