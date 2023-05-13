#!/bin/env python

import argparse
import codecs
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import urllib.parse

from hashlib import sha256


def fetch_adoptium(version: str, architecture: str = "x64"):
    query = {
        "architecture": architecture,
        "image_type": "jdk",
        "os": "linux",  # linux os only for now :tm:
        "vendor": "eclipse",
    }

    api_url = "https://api.adoptium.net/v3/assets/latest/%s/hotspot" % version
    api_url = api_url + '?' + urllib.parse.urlencode(query)

    req = urllib.request.Request(api_url)
    req.add_header('User-Agent', 'dl-python-script/0.1')

    r = urllib.request.urlopen(req)
    data = json.loads(r.read().decode('utf-8'))

    if len(data) <= 0:
        raise Exception("no adoptium jdk/jre assets found")

    return data[-1]


def download_asset(url: str, tempdir: str) -> str:
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'dl-python-script/0.1')

    with urllib.request.urlopen(req) as response:
        filename = response.headers.get_filename()
        if filename is None:
            raise Exception("filename missing for url: %s", url)

        asset_name = os.path.join(tempdir, filename)
        print("downloading asset: %s to %s" % (url, asset_name))

        with open(asset_name, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

        return asset_name


def verify_asset(asset) -> bool:
    # checksum
    checksum = codecs.decode(asset['checksum'], 'hex')
    h = sha256()

    with open(asset['package'], 'rb') as asset:
        while chunk := asset.read(8192):
            h.update(chunk)

    # todo later: signature check; requires gpg and trusted key from net.adoptium.net
    return checksum == h.digest()


def extract_asset(asset_package) -> str:
    if asset_package.endswith('.tar.gz') or asset_package.endswith('.tgz'):
        opener, mode = tarfile.open, 'r:gz'
    elif asset_package.endswith('tar.bz2') or asset_package.endswith('.tbz'):
        opener, mode = tarfile.open, 'r:bz2'
    else:
        raise ValueError("unexpected asset archive: %s" % asset_package)

    archive = opener(asset_package, mode)

    try:
        asset_dir = os.path.dirname(asset_package)
        root_dirname = next(
            (x for x in archive.getmembers() if x.isdir()), None)
        # todo filter named parameter only exists >= python 3.11.4s
        archive.extractall(asset_dir)
        return os.path.join(asset_dir, root_dirname.name)
    finally:
        archive.close()


def system_facts():
    info = {}
    info['platform'] = platform.system()
    info['machine'] = platform.machine()

    architecture_map = {'AMD64': 'x64',
                        'x86_64': 'x64', 'i386': 'x32', 'x86': 'x86'}
    info['architecture'] = architecture_map.get(info['machine'], None)
    return info


def get_jdk(asset_dir: str):
    sys_facts = system_facts()
    java_versions = ['11', '16']

    assets = []

    # hardcoded to 'linux' anyways
    # if sys_facts['platform'] != 'Linux':
    # raise Exception('unsupported platform, only supporting Linux');

    if sys_facts['architecture'] is None:
        raise Exception('unsupported architecture, got: %s' %
                        sys_facts['architecture'])

    for ver in java_versions:
        java_asset = fetch_adoptium(ver, sys_facts['architecture'])
        java_package = java_asset['binary']['package']

        if java_package.get('checksum') is None:
            print("skipping, no checksum provided")
            continue

        # if java_package.get('signature_link') is None:
        #   print("skipping, no signature provided")
        #   continue

        with tempfile.TemporaryDirectory() as tmpdirname:
            print('created temporary directory [java %s]: %s' % (
                ver, tmpdirname))

            asset = {}

            asset['name'] = java_package['name']
            asset['checksum'] = java_package['checksum']
            asset['signature'] = download_asset(
                java_package['signature_link'], tmpdirname)
            asset['package'] = download_asset(java_package['link'], tmpdirname)

            if not verify_asset(asset):
                raise Exception('checksum mismatch: java %s' % ver)

            asset['path'] = os.path.join(asset_dir, asset['name'])
            shutil.copy(asset['package'], asset['path'])

            assets.append(asset)

    return assets


# Execute when the module is not initialized from an import statement.
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "directory", help="destination directory to save adoptium jdk assets")
    parser.add_argument(
        "-o", help="json output of downloaded & extracted jdk assets")
    args = parser.parse_args()

    # download!
    dir_path = os.path.abspath(args.directory)
    os.makedirs(dir_path, exist_ok=True)
    assets = get_jdk(dir_path)

    # extract
    extracted_assets = []

    for asset in assets:
        try:
            asset['path'] = extract_asset(asset['path'])
            extracted_assets.append(asset)
        except Exception as ex:
            print(ex)
            continue

    # dump list of extracted assets
    if not args.o:
        print(json.dumps(extracted_assets, sort_keys=False, indent=2))
    else:
        try:
            outputFile = open(args.o, 'w')
            json.dump(extracted_assets, outputFile, sort_keys=False, indent=2)
        except Exception as ex:
            print(ex)
        finally:
            outputFile.close()
