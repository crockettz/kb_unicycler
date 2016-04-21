from __future__ import print_function
import unittest
import os
import time

from os import environ
from ConfigParser import ConfigParser
import psutil

import requests
from biokbase.workspace.client import Workspace as workspaceService  # @UnresolvedImport @IgnorePep8
from biokbase.AbstractHandle.Client import AbstractHandle as HandleService  # @UnresolvedImport @IgnorePep8
from gaprice_SPAdes.gaprice_SPAdesImpl import gaprice_SPAdes
from pprint import pprint


class gaprice_SPAdesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.token = environ.get('KB_AUTH_TOKEN', None)
        cls.ctx = {'token': cls.token,
                   'provenance': [
                        {'service': 'gaprice_SPAdes',
                         'method': 'please_never_use_it_in_production',
                         'method_params': []
                         }],
                   'authenticated': 1}
        config_file = environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('gaprice_SPAdes'):
            cls.cfg[nameval[0]] = nameval[1]
        cls.wsURL = cls.cfg['workspace-url']
        cls.shockURL = cls.cfg['shock-url']
        cls.hs = HandleService(url=cls.cfg['handle-service-url'],
                               token=cls.token)
        cls.wsClient = workspaceService(cls.wsURL, token=cls.token)
        cls.serviceImpl = gaprice_SPAdes(cls.cfg)
        cls.staged = {}
        cls.nodes_to_delete = []
        cls.handles_to_delete = []
        cls.setupTestData()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'wsName'):
            cls.wsClient.delete_workspace({'workspace': cls.wsName})
            print('Test workspace was deleted: ' + cls.wsName)
        for node in cls.nodes_to_delete:
            cls.delete_shock_node(node)

        cls.hs.delete_handles(cls.hs.ids_to_handles(cls.handles_to_delete))
        print('Deleted handles ' + str(cls.handles_to_delete))

    @classmethod
    def getWsName(cls):
        if hasattr(cls, 'wsName'):
            print('returning existing workspace name ' + cls.wsName)
            return cls.wsName
        suffix = int(time.time() * 1000)
        wsName = "test_gaprice_SPAdes_" + str(suffix)
        cls.wsClient.create_workspace({'workspace': wsName})
        cls.wsName = wsName
        print('created workspace ' + wsName)
        return wsName

    def getImpl(self):
        return self.__class__.serviceImpl

    def getContext(self):
        return self.__class__.ctx

    @classmethod
    def delete_shock_node(cls, node_id):
        header = {'Authorization': 'Oauth {0}'.format(cls.token)}
        requests.delete(cls.shockURL + '/node/' + node_id, headers=header,
                        allow_redirects=True)
        print('Deleted shock node ' + node_id)

    # Helper script borrowed from the transform service, logger removed
    @classmethod
    def upload_file_to_shock(cls, file_path):
        """
        Use HTTP multi-part POST to save a file to a SHOCK instance.
        """

        header = dict()
        header["Authorization"] = "Oauth {0}".format(cls.token)

        if file_path is None:
            raise Exception("No file given for upload to SHOCK!")

        with open(os.path.abspath(file_path), 'rb') as dataFile:
            files = {'upload': dataFile}
            print('POSTing data')
            response = requests.post(
                cls.shockURL + '/node', headers=header, files=files,
                stream=True, allow_redirects=True)
            print('got response')

        if not response.ok:
            response.raise_for_status()

        result = response.json()

        if result['error']:
            raise Exception(result['error'][0])
        else:
            return result["data"]

    @classmethod
    def upload_file_to_shock_and_get_handle(cls, test_file):
        '''
        Uploads the file in test_file to shock and returns the node and a
        handle to the node.
        '''
        print('loading file to shock: ' + test_file)
        node = cls.upload_file_to_shock(test_file)
        pprint(node)
        cls.nodes_to_delete.append(node['id'])

        print('creating handle for shock id ' + node['id'])
        handle_id = cls.hs.persist_handle({'id': node['id'],
                                           'type': 'shock',
                                           'url': cls.shockURL
                                           })
        cls.handles_to_delete.append(handle_id)

        md5 = node['file']['checksum']['md5']
        return node['id'], handle_id, md5, node['file']['size']

    @classmethod
    def upload_assembly(cls, key, wsobjname, object_body,
                        fwd_reads, rev_reads=None, kbase_assy=False):
        print('staging data for key ' + key)
        print('uploading forward reads file ' + fwd_reads['file'])
        fwd_id, fwd_handle_id, fwd_md5, fwd_size = \
            cls.upload_file_to_shock_and_get_handle(fwd_reads['file'])
        fwd_handle = {
                      'hid': fwd_handle_id,
                      'file_name': fwd_reads['name'],
                      'id': fwd_id,
                      'url': cls.shockURL,
                      'type': 'shock',
                      'remote_md5': fwd_md5
                      }

        ob = dict(object_body)  # copy
        ob['sequencing_tech'] = 'fake data'
        if kbase_assy:
            wstype = 'KBaseAssembly.PairedEndLibrary'
            ob['handle_1'] = fwd_handle
        else:
            wstype = 'KBaseFile.PairedEndLibrary'
            ob['lib1'] = \
                {'file': fwd_handle,
                 'encoding': 'UTF8',
                 'type': fwd_reads['type'],
                 'size': fwd_size
                 }

        if rev_reads:
            print('uploading reverse reads file ' + rev_reads['file'])
            rev_id, rev_handle_id, rev_md5, rev_size = \
                cls.upload_file_to_shock_and_get_handle(rev_reads['file'])
            rev_handle = {
                          'hid': rev_handle_id,
                          'file_name': rev_reads['name'],
                          'id': rev_id,
                          'url': cls.shockURL,
                          'type': 'shock',
                          'remote_md5': rev_md5
                          }
            if kbase_assy:
                ob['handle_2'] = rev_handle
            else:
                ob['lib2'] = \
                    {'file': rev_handle,
                     'encoding': 'UTF8',
                     'type': rev_reads['type'],
                     'size': rev_size
                     }

        print('Saving object data')
        objdata = cls.wsClient.save_objects({
            'workspace': cls.getWsName(),
            'objects': [
                        {
                         'type': wstype,
                         'data': ob,
                         'name': wsobjname
                         }]
            })[0]
        print('Saved object: ')
        print(objdata)
        cls.staged[key] = objdata

    @classmethod
    def setupTestData(cls):
        print('Shock url ' + cls.shockURL)
        print('WS url ' + cls.wsClient.url)
        print('Handle service url ' + cls.hs.url)
        print('CPUs detected ' + str(psutil.cpu_count()))
        print('Available memory ' + str(psutil.virtual_memory().available))
        print('staging data')
        fwd_reads = {'file': 'data/small.forward.fq',
                     'name': 'test_fwd.fq',
                     'type': 'fastq'}
        rev_reads = {'file': 'data/small.reverse.fq',
                     'name': 'test_rev.fq',
                     'type': 'fastq'}
        int_reads = {'file': 'data/interleaved.fq',
                     'name': 'test_int.fq',
                     'type': '.FQ'}
        cls.upload_assembly('frbasic', 'frbasic', {}, fwd_reads,
                            rev_reads=rev_reads)
        cls.upload_assembly('intbasic', 'intbasic', {}, int_reads)
        cls.upload_assembly('frbasic_kbassy', 'frbasic_kbassy', {},
                            fwd_reads, rev_reads=rev_reads, kbase_assy=True)
        cls.upload_assembly('intbasic_kbassy', 'intbasic_kbassy', {},
                            int_reads, kbase_assy=True)
        print('Data staged.')

    def make_ref(self, object_info):
        return str(object_info[6]) + '/' + str(object_info[0]) + \
            '/' + str(object_info[4])

    # TODO run through code & check paths (look at xform service tests)

    def test_fr_pair_kbfile(self):

        self.run_success(
            ['frbasic'], 'frbasic_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'length': 64822,
               'id': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'md5': '8a67351c7d6416039c6f613c31b10764'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'length': 62607,
               'id': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'md5': 'e99fade8814bdb861532f493e5deddbd'
               }],
             'md5': '09a27dd5107ad23ee2b7695aee8c09d0',
             'fasta_md5': '7f6093a7e56a8dc5cbf1343b166eda67'
             })

    def test_fr_pair_kbassy(self):

        self.run_success(
            ['frbasic_kbassy'], 'frbasic_kbassy_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'length': 64822,
               'id': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'md5': '8a67351c7d6416039c6f613c31b10764'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'length': 62607,
               'id': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'md5': 'e99fade8814bdb861532f493e5deddbd'
               }],
             'md5': '09a27dd5107ad23ee2b7695aee8c09d0',
             'fasta_md5': '7f6093a7e56a8dc5cbf1343b166eda67'
             })

    def test_interlaced_kbfile(self):

        self.run_success(
            ['intbasic'], 'intbasic_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1000_length_274_cov_1.11168_ID_9587',
               'length': 274,
               'id': 'NODE_1000_length_274_cov_1.11168_ID_9587',
               'md5': '1b00037a0f39ff0fcb577c4e7ff72cf1'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1001_length_274_cov_1.1066_ID_9589',
               'length': 274,
               'id': 'NODE_1001_length_274_cov_1.1066_ID_9589',
               'md5': 'c1c853543b2bba9211e574238b842869'
               }],
             'md5': 'affbb138ad3887c7d12e8ec28a9a8d52',
             'fasta_md5': 'b3012dec12e4b6042affc9a933b60f7a'
             }, contig_count=1449)

    def test_interlaced_kbassy(self):

        self.run_success(
            ['intbasic_kbassy'], 'intbasic_kbassy_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1000_length_274_cov_1.11168_ID_9587',
               'length': 274,
               'id': 'NODE_1000_length_274_cov_1.11168_ID_9587',
               'md5': '1b00037a0f39ff0fcb577c4e7ff72cf1'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1001_length_274_cov_1.1066_ID_9589',
               'length': 274,
               'id': 'NODE_1001_length_274_cov_1.1066_ID_9589',
               'md5': 'c1c853543b2bba9211e574238b842869'
               }],
             'md5': 'affbb138ad3887c7d12e8ec28a9a8d52',
             'fasta_md5': 'b3012dec12e4b6042affc9a933b60f7a'
             }, contig_count=1449, dna_source='')

    def test_multiple(self):
        self.run_success(
            ['intbasic_kbassy', 'frbasic'], 'multiple_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1_length_64822_cov_8.54567_ID_29',
               'length': 64822,
               'id': 'NODE_1_length_64822_cov_8.54567_ID_29',
               'md5': '8a67351c7d6416039c6f613c31b10764'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_2_length_62607_cov_8.06011_ID_15',
               'length': 62607,
               'id': 'NODE_2_length_62607_cov_8.06011_ID_15',
               'md5': 'e99fade8814bdb861532f493e5deddbd'
               }],
             'md5': 'a1bfe0a6d53afb2f0a8c186d4265703a',
             'fasta_md5': '5b7d11cf6a1b01cb2857883a5dc74357'
             }, contig_count=6, dna_source='None')

    def test_single_cell(self):

        self.run_success(
            ['frbasic'], 'single_cell_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'length': 64822,
               'id': 'NODE_1_length_64822_cov_8.54567_ID_21',
               'md5': '8a67351c7d6416039c6f613c31b10764'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'length': 62607,
               'id': 'NODE_2_length_62607_cov_8.06011_ID_7',
               'md5': 'e99fade8814bdb861532f493e5deddbd'
               }],
             'md5': '09a27dd5107ad23ee2b7695aee8c09d0',
             'fasta_md5': '7f6093a7e56a8dc5cbf1343b166eda67'
             }, dna_source='single_cell')

    def test_metagenome(self):

        self.run_success(
            ['frbasic'], 'metagenome_out',
            {'contigs':
             [{'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_1_length_64819_cov_8.54977_ID_184',
               'length': 64819,
               'id': 'NODE_1_length_64819_cov_8.54977_ID_184',
               'md5': '319f720b2de1af6dc7f32a98c1d3048e'
               },
              {'description': 'Note MD5 is generated from uppercasing ' +
                              'the sequence',
               'name': 'NODE_2_length_62607_cov_8.06601_ID_257',
               'length': 62607,
               'id': 'NODE_2_length_62607_cov_8.06601_ID_257',
               'md5': '878ed3dfad7ccecd5bdfc8f5c2db00c4'
               }],
             'md5': '5951328d2b25b8d9f6248a9b0aa3c49a',
             'fasta_md5': 'fe801b181101b2be1e64885e167cdfcb'
             }, dna_source='metagenome')

    def test_no_workspace_param(self):

        self.run_error(['foo'], 'out',
                       'workspace_name parameter is required', wsname=None)

    def test_no_workspace_name(self):

        self.run_error(['foo'], 'out',
                       'workspace_name parameter is required', wsname='None')

    def test_no_libs_param(self):

        self.run_error(None, 'out', 'read_libraries parameter is required')

    def test_no_libs_list(self):

        self.run_error('foo', 'out', 'read_libraries must be a list')

    def test_no_libs(self):

        self.run_error([], 'out',
                       'At least one reads library must be provided')

    def test_no_output_param(self):

        self.run_error(['foo'], None,
                       'output_contigset_name parameter is required')

    def test_no_output_name(self):

        self.run_error(['foo'], '',
                       'output_contigset_name parameter is required')

    def run_error(self, libs, output_name, error, wsname=('fake'),
                  dna_source=None):
        if wsname == ('fake'):
            wsname = self.getWsName()

        params = {}
        if (wsname is not None):
            if wsname == 'None':
                params['workspace_name'] = None
            else:
                params['workspace_name'] = wsname

        if (libs is not None):
            params['read_libraries'] = libs

        if (output_name is not None):
            params['output_contigset_name'] = output_name

        if not (dna_source is None):
            params['dna_source'] = dna_source

        with self.assertRaises(ValueError) as context:
            self.getImpl().run_SPAdes(self.getContext(), params)
        self.assertIn(error, str(context.exception))

    def run_success(self, stagekeys, output_name, expected, contig_count=None,
                    dna_source=None):

        if not contig_count:
            contig_count = len(expected['contigs'])

        libs = [self.staged[key][1] for key in stagekeys]
        assyrefs = sorted(
            [self.make_ref(self.staged[key]) for key in stagekeys])

        params = {'workspace_name': self.getWsName(),
                  'read_libraries': libs,
                  'output_contigset_name': output_name
                  }

        if not (dna_source is None):
            if dna_source == 'None':
                params['dna_source'] = None
            else:
                params['dna_source'] = dna_source

        ret = self.getImpl().run_SPAdes(self.getContext(), params)[0]

        report = self.wsClient.get_objects([{'ref': ret['report_ref']}])[0]
        self.assertEqual('KBaseReport.Report', report['info'][2].split('-')[0])
        self.assertEqual(1, len(report['data']['objects_created']))
        self.assertEqual('Assembled contigs',
                         report['data']['objects_created'][0]['description'])
        self.assertIn('Assembled into ' + str(contig_count) +
                      ' contigs', report['data']['text_message'])
        self.assertEqual(1, len(report['provenance']))
        self.assertEqual(
            assyrefs, sorted(report['provenance'][0]['input_ws_objects']))
        self.assertEqual(
            assyrefs,
            sorted(report['provenance'][0]['resolved_ws_objects']))

        cs_ref = report['data']['objects_created'][0]['ref']
        cs = self.wsClient.get_objects([{'ref': cs_ref}])[0]
        self.assertEqual('KBaseGenomes.ContigSet', cs['info'][2].split('-')[0])
        self.assertEqual(1, len(cs['provenance']))
        self.assertEqual(
            assyrefs, sorted(cs['provenance'][0]['input_ws_objects']))
        self.assertEqual(
            assyrefs, sorted(cs['provenance'][0]['resolved_ws_objects']))
        self.assertEqual(output_name, cs['info'][1])

        cs_fasta_node = cs['data']['fasta_ref']
        header = {"Authorization": "Oauth {0}".format(self.token)}
        fasta_node = requests.get(self.shockURL + '/node/' + cs_fasta_node,
                                  headers=header, allow_redirects=True).json()
        self.assertEqual(expected['fasta_md5'],
                         fasta_node['data']['file']['checksum']['md5'])

        self.assertEqual(contig_count, len(cs['data']['contigs']))
        self.assertEqual(output_name, cs['data']['id'])
        self.assertEqual(output_name, cs['data']['name'])
        self.assertEqual(expected['md5'], cs['data']['md5'])
        self.assertEqual('See provenance', cs['data']['source'])
        self.assertEqual('See provenance', cs['data']['source_id'])

        for i, (exp, got) in enumerate(zip(expected['contigs'],
                                           cs['data']['contigs'])):
            print('Checking contig ' + str(i) + ': ' + exp['name'])
            exp['s_len'] = exp['length']
            got['s_len'] = len(got['sequence'])
            del got['sequence']
            self.assertDictEqual(exp, got)
