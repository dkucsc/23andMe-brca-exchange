import getpass
import logging
import os
from optparse import OptionParser

import requests
import flask
from flask import request
from requests_oauthlib import OAuth2Session

import ga4gh.client as g4client


PORT = 5000
API_SERVER = 'api.23andme.com'
BASE_CLIENT_URL = 'http://localhost:%s/' % PORT
DEFAULT_REDIRECT_URI = '%sapp/' % BASE_CLIENT_URL
PAGE_HEADER = "23andMe + GA4GH"
access_token = None

# So we don't get errors if the redirect uri is not https.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = '1'

# Pass in more scopes through the command line, or change these.
DEFAULT_SNPS = ['rs12913832', 'rs3088053', 'rs1000068', 'rs206118', 'rs206115']
DEFAULT_SCOPES = ['names', 'basic'] + DEFAULT_SNPS

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
parser.add_option("-r", "--redirect_uri", dest="redirect_uri", default=DEFAULT_REDIRECT_URI,
                  help="Your client's redirect_uri [%s]" % DEFAULT_REDIRECT_URI)
parser.add_option("-a", "--23andMe-api-server", dest="t23andMe_api_server", default=API_SERVER,
                  help="Almost always: [api.23andme.com]")
parser.add_option("-p", "--select-profile", dest='select_profile', action='store_true', default=False,
                  help='If present, the auth screen will show a profile select screen')
parser.add_option("-f", "--ga4gh-api-server", dest="ga4gh_api_server", help="The GA4GH API server location.")
parser.add_option("-d", "--debug", dest="debug", action="store_true", default=False,
                  help="Whether or not to provide debugging output.")

(options, args) = parser.parse_args()

DEBUG = options.debug

BASE_API_URL = "https://%s" % options.t23andMe_api_server
API_AUTH_URL = '%s/authorize' % BASE_API_URL
API_TOKEN_URL = '%s/token/' % BASE_API_URL

API_SERVER_GA4GH = options.ga4gh_api_server

if options.select_profile:
    API_AUTH_URL += '?select_profile=true'

redirect_uri = options.redirect_uri
client_id = options.client_id
if options.client_secret:
    client_secret = options.client_secret

scopes = options.scopes or DEFAULT_SCOPES

if not options.client_id:
    print "missing param: CLIENT_ID:"
    parser.print_usage()
    print "Please navigate to your developer dashboard [%s/dev/] to retrieve your client_id.\n" % BASE_API_URL
    exit()

if not client_secret:
    print "Please navigate to your developer dashboard [%s/dev/] to retrieve your client_secret." % BASE_API_URL
    client_secret = getpass.getpass("Please enter your client_secret: ")

app = flask.Flask(__name__)


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
    ttam_oauth = OAuth2Session(client_id, redirect_uri=redirect_uri,
                               scope=scopes)
    auth_url, state = ttam_oauth.authorization_url(API_AUTH_URL)
    return flask.render_template('index.html', auth_url=auth_url,
        page_header=PAGE_HEADER, page_title=PAGE_HEADER, client_id=client_id)


def _23andMe_queries(client_id, client_secret, redirect_uri):
    """Handles interaction with the 23andMe API.  Returns the data."""
    global access_token
    if not access_token:
        ttam_oauth = OAuth2Session(client_id, redirect_uri=redirect_uri)
        token_dict = ttam_oauth.fetch_token(API_TOKEN_URL,
                                            client_secret=client_secret,
                                            authorization_response=request.url)

        access_token = token_dict['access_token']

    headers = {'Authorization': 'Bearer %s' % access_token}

    genotype_response = requests.get("%s%s" % (BASE_API_URL, "/1/genotype/"),
                                    params={'locations': ' '.join(DEFAULT_SNPS)},
                                    headers=headers,
                                    verify=False)
    user_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/user/"),
                                    headers=headers,
                                    verify=False)
    names_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/names/"),
                                     headers=headers,
                                     verify=False)
    profilepic_response = requests.get("%s%s" % (BASE_API_URL, "/1/demo/profile_picture/"),
                                     headers=headers,
                                     verify=False)
    return genotype_response, user_response, names_response, profilepic_response

def _ga4gh_queries():
    """Performs queries against the GA4GH server."""
    if DEBUG:
        httpClient = g4client.HttpClient(API_SERVER_GA4GH, logLevel=logging.DEBUG)
    else:
        httpClient = g4client.HttpClient(API_SERVER_GA4GH)
    datasets = list(httpClient.search_datasets())
    variant_sets = list(httpClient.search_variant_sets(dataset_id=datasets[0].id))
    #iterator = httpClient.search_variants(variant_set_id=variant_sets[0].id,
    iterator = httpClient.search_variants(variant_set_id='brca-hg38',
        #reference_name="1", start=45000, end=50000)
        reference_name="13", start=32315650, end=32315660)
    results = list()
    for variant in iterator:
        r = (variant.reference_name, variant.start, variant.end,\
            variant.reference_bases, variant.alternate_bases)
        results.append(r)
    return results

@app.route('/app/')
def app2():
    """Represents our application, which makes use of 2 APIs: 23andMe, and
    BRCA Exchange (via GA4GH)."""
    # Query the 2 APIs and get data responses.
    genotype_response, user_response, names_response, profilepic_response = _23andMe_queries(client_id, client_secret, redirect_uri)
    results = _ga4gh_queries()

    # Process the data.
    user_request_success = False
    if user_response.status_code == 200:
        user_request_success = True
    names_request_success = False
    if names_response.status_code == 200:
        names_request_success = True
    profilepic_request_success = False
    if profilepic_response.status_code == 200:
        profilepic_request_success = True

    if 'first_name' in names_response.json():
        account_first_name = names_response.json()['first_name']
    else:
        account_first_name = "first"
    if 'last_name' in names_response.json():
        account_last_name = names_response.json()['last_name']
    else:
        account_last_name = "last"

    if genotype_response.status_code == 200:
        if 'code' in request.args.to_dict():
            code = request.args.to_dict()['code']
        else:
            code = None
        return flask.render_template('app.html', page_header=PAGE_HEADER,
            genotype_response_json=genotype_response.json(),
            home_url=BASE_CLIENT_URL,
            user_response_json=user_response.json(),
            names_response_json=names_response.json(),
            page_title=PAGE_HEADER, client_id=client_id, code=code,
            ga4gh_results=results, user_request_success=user_request_success,
            names_request_success=names_request_success,
            profilepic_request_success=profilepic_request_success,
            account_first_name=account_first_name,
            account_last_name=account_last_name)
    else:
        genotype_response.raise_for_status()


if __name__ == '__main__':
    app.run(debug=DEBUG, port=PORT)
