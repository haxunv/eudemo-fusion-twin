"""Checks outside Kit; live CAE execution is covered by probe_workflow.py."""

import ast
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_workflow_controls_have_registered_typed_schema(self):
        # USD freezes schema definitions when the first Stage is created. Other
        # tests already use USD, so exercise plugin-before-stage startup in isolation.
        program=textwrap.dedent("""
            import sys,tomllib
            from pathlib import Path
            from pxr import Plug,Usd
            root=Path(sys.argv[1])
            Plug.Registry().RegisterPlugins(str(root/"kit/extensions/fusion.twin.schema/resources"))
            stage=Usd.Stage.CreateInMemory()
            prim=stage.DefinePrim("/World/AppState","Prim")
            assert prim.AddAppliedSchema("FusionTwinAppStateAPI")
            manifest=tomllib.loads((root/"kit/workflow/workflow.toml").read_text(encoding="utf-8"))
            for name,control in manifest["controls"].items():
                attr=prim.GetAttribute(control["schema_attr"])
                assert attr,name
                assert attr.Get() is not None,name
                if "values" in control:
                    assert list(attr.GetMetadata("allowedTokens"))==control["values"],name
            assert manifest["outputs"]["plasma_temperature"]["units"]=="keV"
        """)
        result=subprocess.run([sys.executable,"-c",program,str(ROOT)],capture_output=True,
                              text=True,encoding="utf-8",errors="replace",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_profile_volume_preserves_units_axisymmetry_and_cut(self):
        path=ROOT/"kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py"
        source=ast.parse(path.read_text(encoding="utf-8"))
        function=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=="_sample_volume")
        namespace={"np":np,"GRID_ORIGIN":(-64,-64,-56),"GRID_SPACING":(28/128,28/128,.15),
                   "GRID_DIMENSIONS":(128,128,112)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),"exec"),namespace)
        radius,height=np.linspace(2,4,9),np.linspace(-1,1,7)
        r,z=np.meshgrid(radius,height,indexing="ij")
        points=np.c_[r.ravel(),np.zeros(r.size),z.ravel()]
        # Every node belongs to the prescribed profile support.
        triangles=np.arange(r.size).reshape(-1,3)
        data={"slice_points":points,"slice_triangles":triangles,
              "slice_temperature_keV":np.full(r.size,12.,dtype=np.float32)}
        values,origin,spacing=namespace["_sample_volume"](data,0)
        self.assertEqual(values.shape,(128,128,112))
        self.assertAlmostEqual(float(values.max()),12)
        np.testing.assert_allclose(values,values[::-1,:,:],atol=1e-5)
        np.testing.assert_allclose(values,values[:,::-1,:],atol=1e-5)
        cut,_,_=namespace["_sample_volume"](data,90)
        self.assertLess(np.count_nonzero(cut),np.count_nonzero(values))
        self.assertAlmostEqual(float(cut.max()),12)
        self.assertTrue(np.all(cut>=0))
        np.testing.assert_allclose(np.asarray(origin)+np.asarray(spacing)*(np.asarray(values.shape)-1),(13.890625,13.890625,8.325))
        z_coordinates=origin[2]+np.arange(values.shape[2])*spacing[2]
        self.assertFalse(np.any(values[:,:,np.abs(z_coordinates)>1]))


if __name__=="__main__":
    unittest.main()
