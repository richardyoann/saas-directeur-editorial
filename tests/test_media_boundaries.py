"""Import ownership is an executable architectural constraint for production modules."""
import ast
from pathlib import Path
import unittest


def imports(path):
    tree = ast.parse(Path(path).read_text())
    return [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]


class MediaBoundaryTests(unittest.TestCase):
    def test_domain_does_not_import_transport_or_adapters(self):
        files = [*Path('editorial/media').glob('*.py'), Path('editorial/media_rules.py'),
                 Path('editorial/image_verification.py')]
        forbidden = ('apps', 'infrastructure', 'fastapi', 'starlette', 'psycopg', 'boto3', 'httpx')
        for file in files:
            with self.subTest(file=str(file)):
                self.assertFalse([name for name in imports(file) if name.split('.')[0] in forbidden])

    def test_adapters_do_not_reimport_legacy_facades(self):
        for file in Path('infrastructure').rglob('*.py'):
            with self.subTest(file=str(file)):
                self.assertFalse(set(imports(file)) & {'editorial.visuals', 'editorial.media_storage', 'editorial.store', 'editorial.api'})

    def test_sql_owner_is_independent_of_storage_and_renderer(self):
        names = imports('infrastructure/persistence/media_repository.py')
        self.assertFalse([n for n in names if n.startswith(('infrastructure.media', 'infrastructure.images', 'apps.'))])
        for file in ('editorial/media/application.py', 'apps/api/media.py'):
            tree = ast.parse(Path(file).read_text())
            self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                              and n.attr == 'execute' and isinstance(n.value, ast.Name)
                              and n.value.id in {'conn', 'connection'}])
        tree = ast.parse(Path('editorial/store.py').read_text())
        names = {'visual_plan', 'begin_image', 'finish_image', 'image_audit_counts',
                 'image_asset', 'list_media', 'record_media'}
        for method in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names):
            self.assertFalse([n for n in ast.walk(method) if isinstance(n, ast.Attribute) and n.attr == 'execute'])

    def test_media_adapters_have_no_import_cycles(self):
        files = [*Path('editorial/media').glob('*.py'), *Path('infrastructure').rglob('*.py'),
                 Path('editorial/media_rules.py'), Path('editorial/image_verification.py')]
        modules = {str(f.with_suffix('')).replace('/', '.'): f for f in files}
        graph = {name: {dep for dep in imports(file) if dep in modules} for name, file in modules.items()}
        active, done = set(), set()
        def visit(name):
            self.assertNotIn(name, active, 'Circular module dependency: ' + name)
            if name in done:
                return
            active.add(name)
            for child in graph[name]:
                visit(child)
            active.remove(name)
            done.add(name)
        for name in graph:
            visit(name)


    def test_historical_facades_export_canonical_implementations(self):
        from editorial import visuals, media_storage
        from infrastructure.images import sdcpp
        from infrastructure.media import images, s3
        self.assertIs(visuals.render_png, sdcpp.render_png)
        self.assertIs(visuals.save_png, images.save_png)
        self.assertIs(visuals.load_png, images.load_png)
        for name in ('put_file', 'get_file', 'object_key', 'MediaStorageError'):
            self.assertIs(getattr(media_storage, name), getattr(s3, name))
