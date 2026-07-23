from pathlib import Path
import subprocess,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
class SkillStructureTests(unittest.TestCase):
    def test_repository_skill_validation(self):
        result=subprocess.run([sys.executable,str(ROOT/"scripts/validate_skills.py")],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,msg=result.stdout+result.stderr)
    def test_orchestrator_exists(self):
        self.assertTrue((ROOT/"skills/doctore-orchestrator/SKILL.md").exists())
    def test_no_legacy_shared_skill_files(self):
        self.assertFalse((ROOT/"skills/shared").exists())
if __name__=="__main__": unittest.main()
