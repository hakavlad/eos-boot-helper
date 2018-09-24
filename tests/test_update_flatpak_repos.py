#!/usr/bin/python3
"""
Tests eos-update-flatpak-repos
"""

import importlib.util
import importlib.machinery
import tempfile
import textwrap

from .util import BaseTestCase, system_script
import gi

gi.require_version("OSTree", "1.0")
from gi.repository import Gio, OSTree  # noqa: E402


# Import script as a module, despite its filename not being a legal module name
spec = importlib.util.spec_from_loader(
    "eufr",
    importlib.machinery.SourceFileLoader(
        "eufr", system_script("eos-update-flatpak-repos")
    ),
)
eufr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eufr)


class TestMangleDesktopFile(BaseTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        self.repo = OSTree.Repo.new(Gio.File.new_for_path(self.tmp.name))
        self.repo.set_disable_fsync(True)
        self.repo.create(OSTree.RepoMode.BARE_USER_ONLY)

        self.mtree = OSTree.MutableTree()

    def tearDown(self):
        self.tmp.cleanup()

    def _ensure_dirs(self, mtree, *dirs):
        for name in dirs:
            _, mtree = mtree.ensure_dir(name)
        return mtree

    def test_rename_empty_desktop(self):
        '''No keys we care about'''
        orig_name = "com.example.Hello.desktop"
        orig_data = textwrap.dedent(
            """
            [Desktop Entry]
            """
        ).strip()

        expected_name = "org.example.Hi.desktop"
        expected_data = textwrap.dedent(
            """
            [Desktop Entry]
            X-Flatpak-RenamedFrom=com.example.Hello.desktop;
            """
        ).strip()

        self._test_simple(orig_name, orig_data, expected_name, expected_data)

    def test_rename_main_desktop(self):
        orig_name = "com.example.Hello.desktop"
        orig_data = textwrap.dedent(
            """
            [Desktop Entry]
            DBusActivatable=true
            Icon=com.example.Hello
            X-Flatpak-RenamedFrom=net.example.Howdy.desktop;
            """
        ).strip()

        expected_name = "org.example.Hi.desktop"
        expected_data = textwrap.dedent(
            """
            [Desktop Entry]
            Icon=org.example.Hi
            X-Flatpak-RenamedFrom=net.example.Howdy.desktop;com.example.Hello.desktop;
            """
        ).strip()

        self._test_simple(orig_name, orig_data, expected_name, expected_data)

    def test_rename_extra_desktop(self):
        orig_name = "com.example.Hello.Again.desktop"
        orig_data = textwrap.dedent(
            """
            [Desktop Entry]
            Icon=com.example.Hello.Next
            """
        ).strip()

        expected_name = "org.example.Hi.Again.desktop"
        expected_data = textwrap.dedent(
            """
            [Desktop Entry]
            Icon=org.example.Hi.Next
            X-Flatpak-RenamedFrom=com.example.Hello.Again.desktop;
            """
        ).strip()

        self._test_simple(orig_name, orig_data, expected_name, expected_data)

    def test_rename_vendor_desktop(self):
        """The Menu Specification introduces the concept of a vendor prefix. In short,
        XDG_DATA_DIR/applications/vendor/foo.desktop should be treated as if it were
        XDG_DATA_DIR/applications/vendor-foo.desktop. This concept was embraced by the
        KDE games we shipped, with a 'kde4' vendor prefix."""
        orig_name = "com.example.Hello.desktop"
        orig_data = textwrap.dedent(
            """
            [Desktop Entry]
            """
        ).strip()

        expected_name = "org.example.Hi.desktop"
        expected_data = textwrap.dedent(
            """
            [Desktop Entry]
            X-Flatpak-RenamedFrom=kde4-com.example.Hello.desktop;
            """
        ).strip()

        # Store the original file in the tree
        kde4_path = ('export', 'share', 'applications', 'kde4')
        self._put_file(kde4_path, orig_name, orig_data)

        # Rename the contents of the export/ directory
        _, export = self.mtree.ensure_dir("export")
        eufr.rename_exports(self.repo, export, "com.example.Hello", "org.example.Hi")

        # Check the kde4/ directory is now empty. In theory we might like the migration
        # script to have deleted it, but the dangling empty directory will go away as
        # soon as the user updates to the Flathub version of the app.
        files = self._mkdir_p(kde4_path).get_files()
        self.assertEqual(list(files.keys()), [])

        # Check the applications/ subdirectory is as we expect
        desktop_path = ('export', 'share', 'applications')
        files = self._mkdir_p(desktop_path).get_files()
        self.assertEqual(list(files.keys()), [expected_name])
        _, stream, info, _ = self.repo.load_file(files[expected_name])
        bytes_ = stream.read_bytes(info.get_size())
        self.assertEqual(bytes_.get_data().decode("utf-8").strip(), expected_data)

    def _mkdir_p(self, path):
        mtree = self.mtree
        for name in path:
            _, mtree = mtree.ensure_dir(name)
        return mtree

    def _put_file(self, parents, name, data):
        data_bytes = data.encode("utf-8")
        stream = Gio.MemoryInputStream.new_from_data(data_bytes)
        info = Gio.FileInfo()
        info.set_size(len(data_bytes))
        info.set_name(name)

        directory = self._mkdir_p(parents)
        eufr.mtree_add_file(self.repo, directory, stream, info)

    def _test_simple(self, orig_name, orig_data, expected_name, expected_data):
        # Store the original file in the tree
        desktop_path = ('export', 'share', 'applications')
        self._put_file(desktop_path, orig_name, orig_data)

        # Rename the contents of the export/ directory
        _, export = self.mtree.ensure_dir("export")
        eufr.rename_exports(self.repo, export, "com.example.Hello", "org.example.Hi")

        # Check the applications/ subdirectory is as we expect
        files = self._mkdir_p(desktop_path).get_files()
        self.assertEqual(list(files.keys()), [expected_name])
        _, stream, info, _ = self.repo.load_file(files[expected_name])
        bytes_ = stream.read_bytes(info.get_size())
        self.assertEqual(bytes_.get_data().decode("utf-8").strip(), expected_data)
