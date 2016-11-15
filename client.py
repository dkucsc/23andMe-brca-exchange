import getpass
import logging
import sys
import re
import pickle
import json
import csv
import os
from optparse import OptionParser

import google.protobuf.json_format as json_format
import requests
import flask
from flask import request
from requests_oauthlib import OAuth2Session

from ga4gh_client import client as g4client
from ga4gh.exceptions import RequestNonSuccessException


PORT = 5000
CACHE_LOCATION = "G423andMe.cache"
API_SERVER = 'api.23andme.com'
BASE_CLIENT_URL = 'http://localhost:%s/' % PORT
DEFAULT_REDIRECT_URI = '%sapp' % BASE_CLIENT_URL
PAGE_HEADER = "23andMe + GA4GH"
#REFERENCE_NAMES = [str(x) for x in range(1, 23)] + ['X', 'Y', 'MT']
REFERENCE_NAMES = ["13", "17"]
access_token = None

# So we don't get errors if the redirect uri is not https.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = '1'

# Pass in more scopes through the command line, or change these.
DEFAULT_SNPS = ['rs12913832', 'rs3088053', 'rs1000068', 'rs206118', 'rs206115', 'rs3094315', 'i3000001']
DEFAULT_SCOPES = ['names', 'basic', 'email', 'analyses', 'genomes'] + DEFAULT_SNPS

# The program will ask for a client_secret if you choose to not hardcode one
# here.
client_secret = None

parser = OptionParser(usage="usage: %prog -i CLIENT_ID [options]")
parser.add_option("-i", "--client-id", dest="client_id", default='',
                  help="Your client_id [REQUIRED]")
parser.add_option('-s', '--scopes', dest='scopes', action='append', default=[],
                  help='Your requested scopes. Eg: -s basic -s rs12913832')
parser.add_option("-c", "--client-secret", dest='client_secret',
                  help='The client secret')
parser.add_option("-r", "--redirect_uri", dest="redirect_uri", default=DEFAULT_REDIRECT_URI, help="Your client's redirect_uri [%s]" % DEFAULT_REDIRECT_URI)
parser.add_option("-a", "--23andMe-api-server", dest="t23andMe_api_server", default=API_SERVER, help="Almost always: [api.23andme.com]")
parser.add_option("-p", "--select-profile", dest='select_profile', action='store_true', default=False, help='If present, the auth screen will show a profile select screen')
parser.add_option("-f", "--ga4gh-api-server", dest="ga4gh_api_server", help="The GA4GH API server location.")
parser.add_option("-d", "--debug", dest="debug", action="store_true", default=False,
                  help="Whether or not to provide debugging output.")
parser.add_option("-k", "--snps-data", dest='snps_data',
                  help='A SNPS data file to use.')

(options, args) = parser.parse_args()


DEBUG = options.debug

BASE_API_URL = "https://%s" % options.t23andMe_api_server
API_AUTH_URL = '%s/authorize' % BASE_API_URL
API_TOKEN_URL = '%s/token/' % BASE_API_URL

API_SERVER_GA4GH = options.ga4gh_api_server

if options.select_profile:
    API_AUTH_URL += '?select_profile=true'

if not options.snps_data:
    print("Should specify --snps-data option.")
    sys.exit(1)
SNPS_DATA_FILE = options.snps_data

redirect_uri = options.redirect_uri
client_id = options.client_id
if options.client_secret:
    client_secret = options.client_secret


def _compute_locations_from_start(start=0, end=1234, reference_name="13", s=""):
    """Computes a more reasonable list of SNPs than DEFAULT_SNPS.
    """
    print("looking for snps")
    print(start, end, reference_name)
    cross = []
    found_header = False
    with open(s, 'r') as fh:
        reader = csv.reader(fh, delimiter='\t')
        for row in reader:
            if not row[0].startswith('#'):
                if not found_header:
                    found_header = True
                    continue
                index, snp, ch, p = row[0], row[1], row[2], row[3]
                p = int(p)
                if ch == reference_name and p > start and p < end:
                    cross.append((snp, p))
    print "Crosses: %s" % len(cross)
    #return cross if len(cross) > 0 else ' '.join(DEFAULT_SNPS)
    #return cross + ' '.join(DEFAULT_SNPS) + scopes
    return cross


def _g4_queries():
    """Performs queries against the GA4GH server."""
    if DEBUG:
        httpClient = g4client.HttpClient(API_SERVER_GA4GH, logLevel=logging.DEBUG)
    else:
        httpClient = g4client.HttpClient(API_SERVER_GA4GH)
    # There is currently only 1 dataset available in BRCA, but we'll be robust
    # and iterate as if there were more.
    datasets = list(httpClient.search_datasets())
    results = list()
    for dataset in datasets:
        # There should be 3 variant sets; we're only concerned with hg37 for
        # now though.
        variant_sets = list(httpClient.search_variant_sets(dataset_id=dataset.id))
        variant_set = filter(lambda x: x.id == 'brca-hg37', variant_sets)[0]
        brca2_start = 32889611
        for reference_name in REFERENCE_NAMES:
            iterator = httpClient.search_variants(variant_set_id=variant_set.id, reference_name=reference_name, start=brca2_start, end=brca2_start+2000)
            #iterator = httpClient.search_variants(variant_set_id=variant_set.id, reference_name=reference_name, start=105598600, end=105598700)
                #reference_name=reference_name, start=32315650, end=32315660)
                #reference_name="13", start=0, end=500000)
            for variant in iterator:
                r = (variant.reference_name, variant.start, variant.end,\
                    variant.reference_bases, variant.alternate_bases, variant.id,\
                    variant.info, variant.names)
                #r = variant
                results.append(r)
    return (datasets, variant_sets, results)


datasets, variant_sets, g4results = _g4_queries()
locations = _compute_locations(g4results, SNPS_DATA_FILE)
print "Locations: %s" % locations
scopes = options.scopes or (DEFAULT_SCOPES + locations)
print "Scopes: %s" % scopes

if not options.client_id:
    print "missing param: CLIENT_ID:"
    parser.print_usage()
    print "Please navigate to your developer dashboard [%s/dev/] to retrieve your client_id.\n" % BASE_API_URL
    exit()

if not client_secret:
    print "Please navigate to your developer dashboard [%s/dev/] to retrieve your client_secret." % BASE_API_URL
    client_secret = getpass.getpass("Please enter your client_secret: ")

app = flask.Flask(__name__)
app.config['SECRET_KEY'] = 'abc'

@app.route('/variants/search/')
def search_variants():
    # flaskrequest # search variants request
    # use variant_set_id=brca-hg37 because .data is in that
    # pass all the arguments to the ga4gh client
    # send to brca exchange server

    # response from brca exchange
    # each variant will have variant.start, variant.end, variant.reference_name
    # look up the variants by position and chromosome in the snp.data file

    # construct a 23andme request using the rs identifier found in the data file
    # add the 23andme metadata into the variant.info

    # reassemble response, change variants in place?
    # return ga4gh response, "hydrated" brca response

    # Enter login credentials
    # Load empty table
    # Request first range
    # Add to table... iteratively

    # multiple profiles on demo account, just choose first?
    # TODO Render multiple profiles
    # Can select profile with /demo/genotypes/PROFILE_ID
    pass


@app.route('/')
def index():
    """Here, we authenticate the user before transitioning to the app.  There
    should be no way of getting to the app without this step."""
    start = int(flask.request.args.get('start', 32889611))
    end = int(flask.request.args.get('end', 32889611 + 1000))
    reference_name = str(flask.request.args.get('reference_name', "13"))
    ttam_oauth = OAuth2Session(client_id, redirect_uri="http://localhost:5000/app/?start={}&end={}&reference_name={}".format(start, end, reference_name),
                               scope=scopes)
    auth_url, state = ttam_oauth.authorization_url(API_AUTH_URL)
    return flask.render_template('index.html', auth_url=auth_url,
        page_header=PAGE_HEADER, page_title=PAGE_HEADER, client_id=client_id)


@app.route('/app/')
def variants():
    flask.session['23code'] = flask.request.args.get('code')
    start = int(flask.request.args.get('start', 32889611))
    end = int(flask.request.args.get('end', 32889611 + 1000))
    reference_name = str(flask.request.args.get('reference_name', "13"))
    
    # Get GA4GH variants
    g4 = g4client.HttpClient(API_SERVER_GA4GH)
    # could take a long time for large regions beware, maybe kick out if a too large region
    # is requested
    variants = list(g4.search_variants(variant_set_id="brca-hg37", start=start, end=end, reference_name=reference_name))
    
    locations = _compute_locations_from_start(start=start, end=end, reference_name=reference_name, s=SNPS_DATA_FILE)
    
    print(locations)
    global access_token
    if not access_token:
        ttam_oauth = OAuth2Session(client_id, redirect_uri="http://localhost:5000/app/")
        token_dict = ttam_oauth.fetch_token(API_TOKEN_URL,
                                            client_secret=client_secret,                                            authorization_response=request.url)

        access_token = token_dict['access_token']
    
    headers = {'Authorization': 'Bearer %s' % access_token}

    user_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/user/"),
                                    headers=headers,
                                    verify=True)
    genotype_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/genotypes/SP1_MOTHER_V4/"),
                                    params={'locations': " ".join(locations), 'format': 'embedded'},
                                    headers=headers,
                                    verify=True)
    genotype_response2 = requests.get("%s%s" % (BASE_API_URL, "/1/demo/genotypes/SP1_FATHER_V4/"),
                                    params={'locations': locations},
                                    headers=headers,
                                    verify=True)
    names_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/names/"),
                                    headers=headers,
                                    verify=True)
    profilepic_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/profile_picture/SP1_FATHER_V4/"),
                                    headers=headers,
                                    verify=True)
    family_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/family_members/"),
                                    headers=headers,
                                    verify=True)

    for profile in genotype_response.json():
        for call in profile['genotypes']:
            for location in locations:
                if call['location'] == location[0]:
                    for variant in variants:
                        if variant.start == location[1]:
                            print("brca and 23andme have {}".format(location[0]))
                            print(variant.info["Allele_Frequency"])
                            print("Individual presented: " + call['call'])

    #print(genotype_response.json())
    #print(variants)
    return flask.jsonify({"23andme": genotype_response.json(), "g4": [json_format._MessageToJsonObject(v, True) for v in variants], "locations": locations, "query": {"start": start, "end": end, "reference_name": reference_name}})


if __name__ == '__main__':
    app.run(debug=DEBUG, port=PORT)
