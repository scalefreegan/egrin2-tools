#!/usr/bin/env python

"""Do all steps to assemble a cMonkey2 ensemble.

Example:

python assembler.py --organism eco --ratios /Users/abrooks/Desktop/Active/Eco_ensemble_python_m3d/ratios_eco_m3d.tsv.gz --targetdir /Users/abrooks/Desktop/Active/Eco_ensemble_python_m3d/ --ncbi_code 511145 --ensembledir /Users/abrooks/Desktop/Active/Eco_ensemble_python_m3d/eco-ens-m3d/ --col_annot /Users/abrooks/Desktop/Active/Eco_ensemble_python_m3d/E_coli_v4_Build_6.experiment_feature_descriptions.tsv.gz --n_resamples 0

python assembler.py --organism eco --ratios ./ratios_eco_m3d.tsv.gz --targetdir ./ --ncbi_code 511145 --ensembledir ./eco-ens-m3d/ --col_annot ./E_coli_v4_Build_6.experiment_feature_descriptions.tsv.gz --n_resamples 0

python assembler.py --organism mtu --ratios ./20141130.MTB.all.ratios.csv.gz --targetdir ./ --ncbi_code 83332 --ensembledir ./  --n_resamples 1000


"""

__author__ = "Aaron Brooks"
__copyright__ = "Copyright 2014, cMonkey2"
__credits__ = ["Aaron Brooks"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Aaron Brooks"
__email__ = "brooksan@uw.edu"
__status__ = "Development"

import argparse
import os, sys, stat
import itertools

from assemble.sql2mongoDB import *
from assemble.makeCorems import * 
from assemble.resample import *

QSUB_TEMPLATE_HEADER_CSH = """#!/bin/csh

"""

QSUB_TEMPLATE_CSH = """#$ -S /bin/csh
#$ -N %(name)s
#$ -o 'out_messages.txt'
#$ -e 'out_messages.txt'
#$ -m be
#$ -q baliga
#$ -P Bal_%(user)s
#$ -l hostname="baliga2|baliga3"
#$ -M %(user)s@systemsbiology.org
#$ -cwd
#$ -pe serial 1
#$ -l mem_free=4G

python resample.py --host %(host)s --db %(db)s --n_rows %(n_rows)i --n_resamples %(n_resamples)i --port %(port)i

"""

RUN_ALL_TEMPLATE = """#!/bin/bash
for FILE in %s *; do
        qsub $FILE
done
"""

RUN_INFO_TEMPLATE = """[ General ensemble info ]

assembly_date_utc: %(date)s
compiled_by: %(user)s
organism: %(organism)s
ncbi_code: %(ncbi_code)s
host: %(host)s
port: %(port)s
db: %(db)s

[ Corem parameters ]

backbone_pval: %(backbone_pval)s
link_comm_score: %(link_comm_score)s
link_comm_increment: %(link_comm_increment)s
link_comm_density_score: %(link_comm_density_score)s
corem_size_threshold: %(corem_size_threshold)s

[ Condition resamples ]

n_resamples: %(n_resamples)s
"""

DESCRIPTION = """assemble.py - prepare cluster runs"""

if __name__ == '__main__':

	import argparse
	import os
	import itertools

	parser = argparse.ArgumentParser(description=DESCRIPTION)
	parser.add_argument('--organism', required=True, type=str, help="3 letter organism code")
	parser.add_argument('--ratios', required=True, help="Path to ratios file. Should be 'raw' (normalized) ratios, not the standardized ratios used by cMonkey")
	parser.add_argument('--targetdir', required=True, help="Storage path for MongoDB and corem data")
	parser.add_argument('--ncbi_code', required=True, help="NCBI organism code")
	parser.add_argument('--cores', default=3, type=int, help="Number local cores to use for corem C++ scripts")
	parser.add_argument('--ensembledir', default=None, help="Path to ensemble runs. Default: cwd")
	parser.add_argument('--col_annot', default=None, help="Tab-delimited file with experiment annotations")
	parser.add_argument('--host', default="localhost", help="MongoDB host. Default 'localhost'")
	parser.add_argument('--port', default=27017, help="MongoDB port", type=int)
	parser.add_argument('--prefix', default=None, help="Ensemble run prefix. Default: *organism*-out-")
	parser.add_argument('--row_annot', default=None, help="Optional row (gene) annotation tab-delimited file. If not specified, annotations will be downloaded from MicrobesOnline using --ncbi_code.")
	parser.add_argument('--row_annot_matchCol', default=None, help="Name of column in row_annot that matches row names in ratios file.")
	parser.add_argument('--gre2motif', default=None, help="Motif->GRE clustering file")
	parser.add_argument('--db', default=None, help="Optional ensemble MongoDB database name")
	parser.add_argument('--genome_annot', default=None, help="Optional genome annotation file. Automatically downloaded from MicrobesOnline using --ncbi_code")
	parser.add_argument('--backbone_pval', default = 0.05, type=float, help="Significance pvalue for gene-gene backbone. Default = 0.05.")
	parser.add_argument('--link_comm_score', default = 0, type=int, help="Scoring metric for link communities" )
	parser.add_argument('--link_comm_increment', default = 0.1, type=float, help="Height increment for cutting agglomerative clustering of link communities" )
	parser.add_argument('--link_comm_density_score', default = 5, type=int,  help="Density score for evaluating link communities")
	parser.add_argument('--corem_size_threshold', default = 3, type=int, help="Defines minimum corem size. Default = 3." )
	parser.add_argument('--n_resamples', default=10000, type=int, help="Number resamples to compute for corem condition assignment. Default = 10,000")
	parser.add_argument('--cluster', default=True, help="Run re-samples on cluster? Boolean.")
	parser.add_argument('--finish_only', default=False, help="Finish corems only. In case session gets dropped")
	parser.add_argument('--user', default=None, help="Cluster user name")

	args = parser.parse_args()

	if args.db is None:
		db = args.organism + "_db"
	else:
		db = dbname

	if args.targetdir is None:
		targetdir = "./"
	else:
		targetdir = args.targetdir

	if args.user is not None:
		user = args.user
	else:
		user = os.getlogin()

	info_d = {
	"date": str( datetime.datetime.utcnow() ),
	"user": user,
	"organism": args.organism,
	"ncbi_code": args.ncbi_code,
	"host": args.host,
	"port": args.port,
	"db": db,
	"backbone_pval": args.backbone_pval,
	"link_comm_score": args.link_comm_score,
	"link_comm_increment": args.link_comm_increment,
	"link_comm_density_score": args.link_comm_density_score,
	"corem_size_threshold": args.corem_size_threshold,
	"n_resamples": args.n_resamples
	}

	with open( os.path.abspath( os.path.join( targetdir, "ensemble.info" ) ) , 'w') as outfile:
		outfile.write( RUN_INFO_TEMPLATE % info_d )

	if args.finish_only:
		sql2mongo = sql2mongoDB( organism = args.organism, host = args.host, port = args.port, ensembledir = args.ensembledir, prefix = args.prefix, ratios_raw = args.ratios, gre2motif = args.gre2motif, col_annot = args.col_annot, ncbi_code = args.ncbi_code, dbname = args.db, db_run_override = None, genome_file = args.genome_annot, row_annot = args.row_annot, row_annot_match_col = args.row_annot_matchCol )
		corems = makeCorems( organism = args.organism, host = args.host, port = args.port, db = db, dbfiles = None, backbone_pval = args.backbone_pval, out_dir = targetdir, n_subs = args.cores, link_comm_score = args.link_comm_score, link_comm_increment = args.link_comm_increment, link_comm_density_score = args.link_comm_density_score, corem_size_threshold = args.corem_size_threshold )
		
		corems.finishCorems()
		
		outfile =  sql2mongo.prefix + str(datetime.datetime.utcnow()).split(" ")[0] + ".mongodump"
		print "Writing EGRIN2 MongoDB to %s" % sql2mongo.targetdir + outfile 
		add_files = " "
		info = os.path.abspath( os.path.join( targetdir, "ensemble.info" ) ) 
		if os.path.isfile(info):
			add_files = add_files + info 
		pdf = os.path.join( corems.out_dir, "density_stats.pdf") 
		if os.path.isfile(pdf):
			add_files = add_files + pdf 
		sql2mongo.mongoDump( sql2mongo.dbname, outfile, add_files = add_files.strip() )

		print "Done"
	else:
		# Initialize to find problems early!!
		sql2mongo = sql2mongoDB( organism = args.organism, host = args.host, port = args.port, ensembledir = args.ensembledir, prefix = args.prefix, ratios_raw = args.ratios, gre2motif = args.gre2motif, col_annot = args.col_annot, ncbi_code = args.ncbi_code, dbname = args.db, db_run_override = None, genome_file = args.genome_annot, row_annot = args.row_annot, row_annot_match_col = args.row_annot_matchCol )
		if len( sql2mongo.db_files ) >0:
		#if True:
			# Merge sql into mongoDB
			sql2mongo.compile()
			corems = makeCorems( organism = args.organism, host = args.host, port = args.port, db = db, dbfiles = None, backbone_pval = args.backbone_pval, out_dir = targetdir, n_subs = args.cores, link_comm_score = args.link_comm_score, link_comm_increment = args.link_comm_increment, link_comm_density_score = args.link_comm_density_score, corem_size_threshold = args.corem_size_threshold )

			# Make corems
			corems.rowRow()
			corems.runCoremCscripts()
			corems.getCorems()
			corems.addCorems()

			if args.cluster:
				client = MongoClient( host = args.host, port= args.port )
				corem_sizes = list( set( [ len( i[ "rows" ] ) for i in client[ db ][ "corem" ].find( {}, {"rows":1} ) ] ) )
				if not os.path.isdir(  os.path.abspath( os.path.join( targetdir, "qsub" ) ) ):
					os.makedirs( os.path.abspath( os.path.join( targetdir, "qsub" ) ) )
				for x in corem_sizes:
					name = args.organism + "_r_" +  str(x)
					with open(os.path.join( os.path.abspath( os.path.join( targetdir, "qsub" ) ), "%s.sh" % name), 'w') as outfile:
						argss = {
							"user": user,
							"n_resamples": args.n_resamples,
							"name": name + ".sh",
							"host": args.host,
							"db": db,
							"n_rows": x,
							"port": args.port
						}
						outfile.write(QSUB_TEMPLATE_HEADER_CSH)
						outfile.write(QSUB_TEMPLATE_CSH % argss )
				with open(os.path.join( os.path.abspath( os.path.join( targetdir, "qsub" ) ), "resample.sh" ), 'w') as outfile:
					outfile.write( RUN_ALL_TEMPLATE % args.organism + "_r_" )
					#os.chmod(os.path.join( os.path.abspath( os.path.join( targetdir, "qsub" ) ), "resample.sh" ), stat.S_IXOTH)
				print "Output Qsub scripts to %s.\n\nTransfer these documents to the cluster. Run 'resample.sh' with resample.py in your working directory to compute all resamples. \n\nOnce this is done, return here to finish processing corems.\n" % os.path.abspath( os.path.join( targetdir, "qsub" ) )
				ready = None
				while ready != "Done":
					ready = raw_input("Please type: 'Done' to continue\n")
			else:
				print "Consider running resamples on a cluster. This will dramatically speed up this step."


			corems.finishCorems()

			outfile =  sql2mongo.prefix + str(datetime.datetime.utcnow()).split(" ")[0] + ".mongodump"
			print "Writing EGRIN2 MongoDB to %s" % sql2mongo.targetdir + outfile 
			add_files = " "
			info = os.path.abspath( os.path.join( targetdir, "ensemble.info" ) ) 
			if os.path.isfile(info):
				add_files = add_files + info 
			pdf = os.path.join( corems.out_dir, "density_stats.pdf") 
			if os.path.isfile(pdf):
				add_files = add_files + pdf 
			sql2mongo.mongoDump( sql2mongo.dbname, outfile, add_files = add_files.strip() )

			print "Done"
		else:	
			print "No cMonkey2 DB files. Please specify --ensembledir"
		