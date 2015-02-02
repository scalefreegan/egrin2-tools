import glob
import os
import sys

import numpy as np
import pandas as pd

import bz2
import sqlite3
import cPickle as pickle   ## make shelve much faster!
import shelve

from cmonkeyobj import cMonkey2 as cm2

class EGRIN2:
    cms = {} ## f: cm2(f) for f in files }
    prefix = 'eco-out-'
    files = None
    tables = {} ##None
    mot_clusters = None
    mot_clusters_df = None

    def __init__( self, prefix, nruns=None ):
        self.prefix = prefix
        self.files = np.sort( np.array( glob.glob( prefix + "???/cmonkey_run.db" ) ) ) # get all cmonkey_run.db files

        self.cms = shelve.open('egrin2_shelf.db', protocol=2, writeback=False)
        keys = self.cms.keys()
        for f in self.files:
            index = os.path.dirname(f).replace(self.prefix,'')
            if index in keys:
                continue
            try:
                print f
                b = cm2(f)
                self.cms[ index ] = b
            except:
                print 'ERROR: %s' % (f)
                e = sys.exc_info()[0]
                print e

            if nruns is not None and len(self.cms) >= nruns:
                break

        #self.tables = { tname: self.concat_tables(tname) for tname in self.cms['001'].tables.keys() }
        self.tables = shelve.open('egrin2_tables_shelf.db', protocol=2, writeback=False)
        keys = self.tables.keys()
        for tname in self.cms['001'].tables.keys():
            if tname in keys:
                continue
            tab = self.concat_tables(tname)
            self.tables[str(tname)] = tab

        #self.cms.close()

    def concat_tables( self, tname ):
        print tname
        row_members = { k: self.cms[k].tables[tname] for k in self.cms.keys() }
        for i in row_members.keys():
            tmp = row_members[i]
            tmp = pd.concat( [ tmp, pd.Series(np.repeat(i,tmp.shape[0])) ], 1 )
            cols = tmp.columns.values; cols[-1] = 'RUNID'; tmp.columns = cols
            row_members[i] = tmp
        row_members = pd.concat( row_members, 0, ignore_index=True, copy=False )
        return row_members

    def make_fimo_dbfiles( self ):
        ## read in fimo tables and store as one big sqlite database, one for each run
        for f in self.files:
            print(f)
            if os.path.isfile( os.path.dirname(f)+'/fimo-outs.db' ):
                continue
            fimo_outs = np.sort( np.array( glob.glob(os.path.dirname(f)+'/fimo-outs/fimo-out-*bz2') ) )
            if len(fimo_outs) <= 0:
                continue
            dfs = {}
            for ff in fimo_outs:
                print '    ' + ff
                try:
                    df = pd.read_table( bz2.BZ2File(ff), sep='\t' )
                    clust_num = int(os.path.basename(ff).split('-')[2].replace('.bz2',''))
                    df = pd.concat( [ df, pd.Series(np.repeat(clust_num,df.shape[0])), \
                                      pd.Series(np.repeat(os.path.dirname(f),df.shape[0])) ], 1 )
                    cols = df.columns.values; cols[-2] = 'cluster'; cols[-1] = 'run_id'; df.columns = cols
                    dfs[ clust_num ] = df ##.append( df )
                except:
                    print 'ERROR'
            dfs = pd.concat( dfs, 0, ignore_index=True, copy=False )
            conn = sqlite3.connect( os.path.dirname(f)+'/fimo-outs.db' )
            dfs.to_sql( 'fimo_out', conn, index=False, if_exists='replace' )
            conn.execute( 'create index idx on fimo_out(start,stop,"p-value")' )
            tmp = pd.read_sql( 'select * from fimo_out limit 10', conn )
            print tmp
            conn.close()

    def get_motifs_at_posn( self, posn, pvalue=1e-5, seqid=None ):
        ## Use the fimo databases created with make_fimo_dbfiles() to select the fimo hits within the given 
        ## coords on the given genome sequence.
        query = 'select * from fimo_out where start <= ? and stop >= ? and "p-value" <= ?'
        params = [posn, posn, pvalue]
        if seqid is not None:
            query = 'select * from fimo_out where start <= ? and stop >= ? and "p-value" <= ? and "sequence name" == seqid'
            params = [posn, posn, pvalue, seqid]

        hits = {}
        for f in self.files:
            try:
                conn = sqlite3.connect( os.path.dirname(f)+'/fimo-outs.db' )
                tmp = pd.read_sql( query, conn, params=params )
                conn.close()
                hits[os.path.dirname(f)] = tmp
            except:
                None
        hits = pd.concat( hits, 0, ignore_index=True, copy=False )
        return hits

    def load_motif_clusters( self, fname='out.mot_metaclustering.txt.I45.txt' ):
        """load motif clusters generated by egrin2/motif_clustering.py
        TBD: return clusters or just the dataframe? """
        fo = open( fname, 'r' )
        lines = fo.readlines()
        fo.close()
        self.mot_clusters = [np.array(line.split()) for line in lines]

        if self.mot_clusters_df is None:
            self.mot_clusters_df = pd.read_table( bz2.BZ2File('motif_clusts.tsv.bz2'), sep='\t' )

    def get_motif_positions( cluster_ind ):
        ## TBD: speed this up; probably need to reindex the fimo tables.
        clust = self.mot_clusters[ cluster_ind ]
        query = 'select * from fimo_out where cluster == ? and "#pattern name" == ?'
        hits = {}
        for c in clust:
            print c
            tmp = c.split('_')
            cl = int(tmp[1])
            mot = int(tmp[2])
            f = tmp[0]
            try:
                conn = sqlite3.connect( f+'/fimo-outs.db' )
                params = [cl, mot]
                tmp = pd.read_sql( query, conn, params=params )
                conn.close()
                hits[c] = tmp
            except:
                None
        hits = pd.concat( hits, 0, ignore_index=True, copy=False )
        return hits

    def get_genes_motif_cluster( self, cluster_ind ):
        from collections import Counter
        ## return count of genes in clusters (TBD: or genes that have motif site from MEME?)
        ## also, need to operon-expand result.
        clust = self.mot_clusters[ cluster_ind ]
        out = []
        for c in np.sort(clust):
            print c
            tmp = c.split('_')
            cm_ind = tmp[0].split('-')[2]
            cl = int(tmp[1])
            mot = int(tmp[2])
            cm = self.cms[ cm_ind ]
            genes = cm.get_rows( cl )
            #sites = cm.get_motif_sites( cl, mot )
            out.extend(genes.tolist())

        out = Counter(out)
        out = pd.DataFrame( {'gene':out.keys(), 'count':out.values()} )
        out = out.sort( ['count'], ascending=False )
        return out

#from egrin2.egrin2obj import EGRIN2 as eg2
#b = eg2('eco-out-')
#np.array([bb.config.getfloat('Rows','scaling_const') for bb in b.cms.values()],np.float)
## Here's how to get nrows for all clusters in the ensemble and plot a histogram:
#tmp=b.tables['row_members'].groupby(['cluster','RUNID']).size()
#pd.DataFrame({'size':tmp}).plot(kind='hist', bins=20)
## And motifs within a location and pvalue. First (only once, do the first line):
#b.make_fimo_dbfiles()
#b.get_motifs_at_posn( 10000, 1e-5 )
#b.load_motif_clusters()
#b.get_genes_motif_clsuter( 30 )
