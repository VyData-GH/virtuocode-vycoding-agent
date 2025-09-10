import os
import subprocess
import asyncio
import json
import tempfile
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

from .base_tool import BaseTool
from models.schemas import TestResult

from config.settings import get_settings
from utils.logger import get_logger

class TestType(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    SMOKE = "smoke"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"

class TestSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class TestFailure(BaseModel):
    test_name: str
    test_file: str
    error_message: str
    severity: TestSeverity = TestSeverity.MEDIUM
    line_number: Optional[int] = None
    suggestion: Optional[str] = None

class TestCoverage(BaseModel):
    total_coverage: float
    files_coverage: Dict[str, float] = {}
    missing_lines: Dict[str, List[int]] = {}
    threshold_met: bool = False

class TestSuite(BaseModel):
    name: str
    test_type: TestType
    files_pattern: str
    timeout: int = 300
    requirements: List[str] = []
    environment: Dict[str, str] = {}

class TestingEngine(BaseTool):
    
    name: str = "testing_engine"
    description: str = """
    Moteur de tests automatisés complet.
    
    Fonctionnalités:
    - Tests unitaires avec pytest
    - Tests d'intégration
    - Smoke tests automatiques
    - Analyse de couverture de code
    - Tests de performance
    - Tests de sécurité
    - Génération automatique de tests
    - Rapport de qualité
    """
    
    working_directory: Optional[str] = Field(default=None)
    test_suites: Dict[TestType, TestSuite] = {}
    
    def __init__(self, **kwargs):
        super().__init__()
        self.settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)
        self._setup_test_suites()
    
    def _setup_test_suites(self):
        self.test_suites = {
            TestType.UNIT: TestSuite(
                name="Tests Unitaires",
                test_type=TestType.UNIT,
                files_pattern="tests/unit/**/*test*.py",
                timeout=300,
                requirements=["pytest", "pytest-cov", "pytest-mock"]
            ),
            TestType.INTEGRATION: TestSuite(
                name="Tests d'Intégration",
                test_type=TestType.INTEGRATION,
                files_pattern="tests/integration/**/*test*.py",
                timeout=600,
                requirements=["pytest", "pytest-asyncio"]
            ),
            TestType.SMOKE: TestSuite(
                name="Smoke Tests",
                test_type=TestType.SMOKE,
                files_pattern="tests/smoke/**/*test*.py",
                timeout=180,
                requirements=["pytest", "requests"]
            ),
            TestType.E2E: TestSuite(
                name="Tests End-to-End",
                test_type=TestType.E2E,
                files_pattern="tests/e2e/**/*test*.py",
                timeout=1200,
                requirements=["pytest", "selenium", "playwright"]
            )
        }
    
    async def _arun(self, action: str, **kwargs) -> Dict[str, Any]:
        try:
            if action == "run_all_tests":
                return await self._run_all_tests(
                    working_directory=kwargs.get("working_directory"),
                    include_coverage=kwargs.get("include_coverage", True)
                )
            elif action == "run_test_type":
                return await self._run_test_type(
                    test_type=TestType(kwargs.get("test_type")),
                    working_directory=kwargs.get("working_directory"),
                    include_coverage=kwargs.get("include_coverage", True)
                )
            elif action == "generate_tests":
                return await self._generate_tests(
                    source_file=kwargs.get("source_file"),
                    working_directory=kwargs.get("working_directory")
                )
            elif action == "analyze_test_coverage":
                return await self._analyze_test_coverage(
                    working_directory=kwargs.get("working_directory")
                )
            elif action == "run_smoke_tests":
                return await self._run_smoke_tests(
                    base_url=kwargs.get("base_url"),
                    working_directory=kwargs.get("working_directory")
                )
            elif action == "security_scan":
                return await self._run_security_scan(
                    working_directory=kwargs.get("working_directory")
                )
            else:
                raise ValueError(f"Action non supportée: {action}")
                
        except Exception as e:
            return self.handle_error(e, f"testing_engine.{action}")
    
    async def _run_all_tests(self, working_directory: str, include_coverage: bool = True) -> Dict[str, Any]:
        self.working_directory = working_directory
        self.logger.info("🧪 Lancement de tous les tests...")
        
        all_results = {}
        total_success = True
        
        for test_type in [TestType.UNIT, TestType.INTEGRATION, TestType.SMOKE]:
            self.logger.info(f"▶️ Exécution des {test_type.value} tests...")
            
            result = await self._run_test_type(test_type, working_directory, include_coverage)
            all_results[test_type.value] = result
            
            if not result.get("success", False):
                total_success = False
        
        coverage_result = None
        if include_coverage:
            coverage_result = await self._analyze_test_coverage(working_directory)
        
        return {
            "success": total_success,
            "test_results": all_results,
            "coverage": coverage_result,
            "summary": self._generate_test_summary(all_results),
            "recommendations": self._generate_recommendations(all_results, coverage_result)
        }
    
    async def _run_test_type(self, test_type: TestType, working_directory: str, include_coverage: bool = True) -> TestResult:
        self.working_directory = working_directory
        suite = self.test_suites.get(test_type)
        
        if not suite:
            raise ValueError(f"Suite de tests non configurée pour {test_type.value}")
        
        await self._setup_test_environment(suite)
        
        cmd = self._build_pytest_command(suite, include_coverage)
        
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                cwd=working_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=suite.timeout
            )
            
            output = stdout.decode('utf-8') if stdout else ""
            
            result = self._parse_pytest_output(output, test_type)
            
            self.logger.info(f"✅ {test_type.value} tests terminés: {result.passed_tests}/{result.total_tests} réussis")
            
            return result
            
        except asyncio.TimeoutError:
            self.logger.error(f"⏰ Timeout pour les {test_type.value} tests")
            return TestResult(
                success=False,
                test_type=test_type.value,
                output="Timeout lors de l'exécution des tests"
            )
        except Exception as e:
            self.logger.error(f"❌ Erreur lors des {test_type.value} tests: {e}")
            return TestResult(
                success=False,
                test_type=test_type.value,
                output=f"Erreur: {str(e)}"
            )
    
    async def _setup_test_environment(self, suite: TestSuite):
        if suite.requirements:
            for requirement in suite.requirements:
                try:
                    import importlib
                    importlib.import_module(requirement.replace("-", "_"))
                except ImportError:
                    self.logger.info(f"📦 Installation de {requirement}...")
                    await self._install_package(requirement)
    
    async def _install_package(self, package: str):
        try:
            process = await asyncio.create_subprocess_shell(
                f"pip install {package}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0:
                self.logger.info(f"✅ {package} installé avec succès")
            else:
                self.logger.warning(f"⚠️ Échec de l'installation de {package}")
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de l'installation de {package}: {e}")
    
    def _build_pytest_command(self, suite: TestSuite, include_coverage: bool) -> str:
        cmd_parts = ["python", "-m", "pytest"]
        
        cmd_parts.append(suite.files_pattern)
        
        cmd_parts.extend([
            "-v",  # verbose
            "--tb=short",  # traceback court
            "--json-report",  # rapport JSON
            "--json-report-file=test_report.json"
        ])
        
        if include_coverage:
            cmd_parts.extend([
                "--cov=.",
                "--cov-report=json:coverage.json",
                "--cov-report=term-missing",
                f"--cov-fail-under={self.settings.test_coverage_threshold}"
            ])
        
        if suite.test_type == TestType.SMOKE:
            cmd_parts.extend(["-x"])  
        elif suite.test_type == TestType.PERFORMANCE:
            cmd_parts.extend(["--benchmark-only"])
        
        return " ".join(cmd_parts)
    
    def _parse_pytest_output(self, output: str, test_type: TestType) -> TestResult:
        result = TestResult(
            success=False,
            test_type=test_type.value,
            output=output
        )
        
        json_report_path = os.path.join(self.working_directory or ".", "test_report.json")
        
        if os.path.exists(json_report_path):
            try:
                with open(json_report_path, 'r') as f:
                    report = json.load(f)
                
                summary = report.get("summary", {})
                result.total_tests = summary.get("total", 0)
                result.passed_tests = summary.get("passed", 0)
                result.failed_tests = summary.get("failed", 0)
                result.skipped_tests = summary.get("skipped", 0)
                result.execution_time = report.get("duration", 0.0)
                result.success = summary.get("failed", 0) == 0
                
                result.failures = self._parse_test_failures(report.get("tests", []))
                
            except Exception as e:
                self.logger.warning(f"Impossible de parser le rapport JSON: {e}")
        
        if result.total_tests == 0:
            result = self._parse_text_output(output, test_type)
        
        return result
    
    def _parse_test_failures(self, tests: List[Dict]) -> List[TestFailure]:
        failures = []
        
        for test in tests:
            if test.get("outcome") == "failed":
                failure = TestFailure(
                    test_name=test.get("nodeid", ""),
                    test_file=test.get("setup", {}).get("filename", ""),
                    error_message=test.get("call", {}).get("longrepr", ""),
                    severity=self._determine_failure_severity(test)
                )
                failures.append(failure)
        
        return failures
    
    def _determine_failure_severity(self, test: Dict) -> TestSeverity:
        error_msg = test.get("call", {}).get("longrepr", "").lower()
        
        if any(keyword in error_msg for keyword in ["security", "auth", "permission"]):
            return TestSeverity.CRITICAL
        elif any(keyword in error_msg for keyword in ["database", "connection", "timeout"]):
            return TestSeverity.HIGH
        elif any(keyword in error_msg for keyword in ["validation", "format", "type"]):
            return TestSeverity.MEDIUM
        else:
            return TestSeverity.LOW
    
    def _parse_text_output(self, output: str, test_type: TestType) -> TestResult:
        result = TestResult(success=False, test_type=test_type.value, output=output)
        
        lines = output.split('\n')
        for line in lines:
            if "passed" in line and "failed" in line:
                import re
                matches = re.findall(r'(\d+) (\w+)', line)
                for count, status in matches:
                    count = int(count)
                    if status == "passed":
                        result.passed_tests = count
                    elif status == "failed":
                        result.failed_tests = count
                    elif status == "skipped":
                        result.skipped_tests = count
                
                result.total_tests = result.passed_tests + result.failed_tests + result.skipped_tests
                result.success = result.failed_tests == 0
                break
        
        return result
    
    async def _analyze_test_coverage(self, working_directory: str) -> Optional[TestCoverage]:
        coverage_file = os.path.join(working_directory, "coverage.json")
        
        if not os.path.exists(coverage_file):
            return None
        
        try:
            with open(coverage_file, 'r') as f:
                coverage_data = json.load(f)
            
            total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0.0)
            
            files_coverage = {}
            missing_lines = {}
            
            for filename, file_data in coverage_data.get("files", {}).items():
                files_coverage[filename] = file_data.get("summary", {}).get("percent_covered", 0.0)
                missing_lines[filename] = file_data.get("missing_lines", [])
            
            return TestCoverage(
                total_coverage=total_coverage,
                files_coverage=files_coverage,
                missing_lines=missing_lines,
                threshold_met=total_coverage >= self.settings.test_coverage_threshold
            )
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'analyse de couverture: {e}")
            return None
    
    async def _run_smoke_tests(self, base_url: str, working_directory: str) -> Dict[str, Any]:
        """Exécute des smoke tests automatiques."""
        self.logger.info(f"🔥 Lancement des smoke tests sur {base_url}")
        
        smoke_tests = [
            {"name": "Health Check", "endpoint": "/health", "method": "GET"},
            {"name": "API Status", "endpoint": "/api/status", "method": "GET"},
            {"name": "Authentication", "endpoint": "/api/auth/test", "method": "POST"}
        ]
        
        results = []
        
        for test in smoke_tests:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    url = f"{base_url.rstrip('/')}{test['endpoint']}"
                    
                    if test['method'] == 'GET':
                        async with session.get(url, timeout=10) as response:
                            success = response.status < 400
                    else:
                        async with session.post(url, timeout=10) as response:
                            success = response.status < 500
                    
                    results.append({
                        "test": test['name'],
                        "success": success,
                        "status_code": response.status,
                        "url": url
                    })
                    
            except Exception as e:
                results.append({
                    "test": test['name'],
                    "success": False,
                    "error": str(e),
                    "url": f"{base_url}{test['endpoint']}"
                })
        
        overall_success = all(r['success'] for r in results)
        
        return {
            "success": overall_success,
            "results": results,
            "base_url": base_url
        }
    
    async def _run_security_scan(self, working_directory: str) -> Dict[str, Any]:
        self.logger.info("🔐 Lancement du scan de sécurité...")
        
        security_checks = [
            {"name": "Bandit Security Scan", "command": "bandit -r . -f json -o security_report.json"},
            {"name": "Safety Dependencies Check", "command": "safety check --json --output safety_report.json"},
            {"name": "Semgrep Security Analysis", "command": "semgrep --config=auto --json --output=semgrep_report.json ."}
        ]
        
        results = []
        
        for check in security_checks:
            try:
                process = await asyncio.create_subprocess_shell(
                    check['command'],
                    cwd=working_directory,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
                
                results.append({
                    "check": check['name'],
                    "success": process.returncode == 0,
                    "output": stdout.decode('utf-8') if stdout else "",
                    "errors": stderr.decode('utf-8') if stderr else ""
                })
                
            except asyncio.TimeoutError:
                results.append({
                    "check": check['name'],
                    "success": False,
                    "error": "Timeout"
                })
            except Exception as e:
                results.append({
                    "check": check['name'],
                    "success": False,
                    "error": str(e)
                })
        
        return {
            "success": all(r['success'] for r in results),
            "security_checks": results
        }
    
    async def _generate_tests(self, source_file: str, working_directory: str) -> Dict[str, Any]:
        self.logger.info(f"🧪 Génération automatique de tests pour {source_file}")
        
        from tools.ai_engine_hub import ai_hub, AIRequest, TaskType
        
        with open(os.path.join(working_directory, source_file), 'r') as f:
            source_code = f.read()
        
        request = AIRequest(
            prompt=f"""
Génère des tests unitaires complets avec pytest pour ce code Python :

```python
{source_code}
```

Génère des tests qui couvrent :
1. Les cas normaux
2. Les cas d'erreur
3. Les cas limites
4. Les mocks nécessaires

Format de sortie : code Python uniquement avec pytest.
""",
            task_type=TaskType.TESTING,
            context={"source_file": source_file, "source_code": source_code}
        )
        
        response = await ai_hub.generate_code(request)
        
        if response.success:
            test_file = source_file.replace('.py', '_test.py')
            test_path = os.path.join(working_directory, 'tests', 'unit', test_file)
            
            os.makedirs(os.path.dirname(test_path), exist_ok=True)
            
            with open(test_path, 'w') as f:
                f.write(response.content)
            
            return {
                "success": True,
                "test_file": test_path,
                "generated_content": response.content,
                "provider_used": response.provider
            }
        else:
            return {
                "success": False,
                "error": response.error
            }
    
    def _generate_test_summary(self, all_results: Dict[str, Any]) -> Dict[str, Any]:
        total_tests = 0
        total_passed = 0
        total_failed = 0
        
        for test_type, result in all_results.items():
            if isinstance(result, dict):
                total_tests += result.get("total_tests", 0)
                total_passed += result.get("passed_tests", 0)
                total_failed += result.get("failed_tests", 0)
        
        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        
        return {
            "total_tests": total_tests,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "success_rate": round(success_rate, 2),
            "overall_success": total_failed == 0
        }
    
    def _generate_recommendations(self, all_results: Dict[str, Any], coverage_result: Optional[TestCoverage]) -> List[str]:
        recommendations = []
        
        for test_type, result in all_results.items():
            if isinstance(result, dict) and result.get("failed_tests", 0) > 0:
                recommendations.append(f"Corriger les échecs dans les {test_type} tests")
        
        if coverage_result and not coverage_result.threshold_met:
            recommendations.append(
                f"Améliorer la couverture de code (actuelle: {coverage_result.total_coverage:.1f}%, "
                f"objectif: {self.settings.test_coverage_threshold}%)"
            )
        if not recommendations:
            recommendations.append("Tous les tests passent ! Considérer l'ajout de tests d'edge cases.")
        
        return recommendations 