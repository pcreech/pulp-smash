# coding=utf-8
"""Tests that verify download of content served by Pulp."""
import hashlib
import unittest
from random import choice
from urllib.parse import urljoin

from requests.exceptions import HTTPError

from pulp_smash import api, config, selectors, utils
from pulp_smash.constants import FILE_FEED_URL, FILE_URL
from pulp_smash.tests.pulp3.constants import (
    DISTRIBUTION_PATH,
    FILE_IMPORTER_PATH,
    FILE_PUBLISHER_PATH,
    REPO_PATH,
)
from pulp_smash.tests.pulp3.file.api_v3.utils import (
    gen_importer,
    gen_publisher,
)
from pulp_smash.tests.pulp3.file.utils import set_up_module as setUpModule  # noqa pylint:disable=unused-import
from pulp_smash.tests.pulp3.pulpcore.utils import gen_distribution, gen_repo
from pulp_smash.tests.pulp3.utils import (
    get_auth,
    get_content_unit_names,
    publish_repo,
    sync_repo,
)


class DownloadContentTestCase(unittest.TestCase, utils.SmokeTest):
    """Verify whether content served by pulp can be downloaded."""

    def test_all(self):  # pylint:disable=too-many-locals
        """Verify whether content served by pulp can be downloaded.

        The process of publishing content is more involved in Pulp 3 than it
        was under Pulp 2. Given a repository, the process is as follows:

        1. Create a publication from the repository. (The latest repository
           version is selected if no version is specified.) A publication is a
           repository version plus metadata.
        2. Create a distribution from the publication. The distribution defines
           at which URLs a publication is available, e.g.
           ``http://example.com/content/pub-name/`` and
           ``https://example.com/content/pub-name/``.

        Do the following:

        1. Create, populate, publish, and distribute a repository.
        2. Select a random content unit in the distribution.
        3. For the schemes "http" and "https":

           * If the distribution has enabled that scheme, then download the
             content unit from Pulp, and verify that the content unit has the
             same checksum when fetched directly from Pulp-Fixtures.
           * If the distribution hasn't enabled that scheme, then verify that
             download requests fail.

        This test targets the following issues:

        * `Pulp #2895 <https://pulp.plan.io/issues/2895>`_
        * `Pulp #3413 <http://pulp.plan.io/issues/3413>`_
        * `Pulp Smash #872 <https://github.com/PulpQE/pulp-smash/issues/872>`_
        """
        cfg = config.get_config()
        client = api.Client(cfg, api.json_handler)
        client.request_kwargs['auth'] = get_auth()
        repo = client.post(REPO_PATH, gen_repo())
        self.addCleanup(client.delete, repo['_href'])
        body = gen_importer()
        body['feed_url'] = urljoin(FILE_FEED_URL, 'PULP_MANIFEST')
        importer = client.post(FILE_IMPORTER_PATH, body)
        self.addCleanup(client.delete, importer['_href'])
        sync_repo(cfg, importer, repo)

        # Create a publisher.
        publisher = client.post(FILE_PUBLISHER_PATH, gen_publisher())
        self.addCleanup(client.delete, publisher['_href'])

        # Create a publication.
        publication = publish_repo(cfg, publisher, repo)
        self.addCleanup(client.delete, publication['_href'])

        # Create a distribution.
        body = gen_distribution()
        body['publication'] = publication['_href']
        distribution = client.post(DISTRIBUTION_PATH, body)
        self.addCleanup(client.delete, distribution['_href'])

        # Pick a file, and download it from both Pulp Fixtures…
        unit_name = choice(get_content_unit_names(repo))
        fixtures_hash = hashlib.sha256(
            utils.http_get(urljoin(FILE_URL, unit_name))
        ).hexdigest()

        # …and Pulp.
        client.response_handler = api.safe_handler
        schemes = ['http']
        if selectors.bug_is_testable(3416, cfg.pulp_version):
            schemes.append('https')
        for scheme in schemes:
            with self.subTest(scheme=scheme):
                unit_url = urljoin(
                    scheme + '://' + distribution['base_url'] + '/',
                    unit_name
                )
                if distribution[scheme]:
                    pulp_hash = hashlib.sha256(
                        client.get(unit_url).content
                    ).hexdigest()
                    self.assertEqual(fixtures_hash, pulp_hash)
                else:
                    if selectors.bug_is_testable(3413, cfg.pulp_version):
                        with self.assertRaises(HTTPError):
                            client.get(unit_url)