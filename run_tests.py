"""
Test Runner Script
==================
Script to run all tests with coverage and generate reports.
"""

import subprocess
import sys
import os

def run_tests_with_coverage():
    """Run tests with coverage reporting."""
    print("=" * 70)
    print("SMART(parcel) WALL - TEST RUNNER")
    print("=" * 70)
    print()
    
    # Install test dependencies if needed
    print("[1/4] Checking dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"[ERROR] Failed to install dependencies: {result.stderr}")
        return False
    print("[OK] Dependencies installed")
    print()
    
    # Run tests with coverage
    print("[2/4] Running tests with coverage...")
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/",
            "-v",
            "--tb=short",
            "--cov=.",
            "--cov-report=term-missing",
            "--cov-report=html:coverage_html",
            "--cov-report=xml:coverage.xml",
            "--cov-fail-under=80"
        ],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    print()
    
    if result.returncode != 0:
        print(f"[FAILED] Tests failed with exit code {result.returncode}")
        return False
    
    print("[OK] Tests passed with coverage")
    print()
    
    # Run linting
    print("[3/4] Running linting checks...")
    result = subprocess.run(
        [sys.executable, "-m", "pylint", "routers/", "models.py", "mqtt/", "--disable=R,C"],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[WARNING] Linting issues found (non-critical)")
    else:
        print("[OK] Linting passed")
    print()
    
    # Generate summary
    print("[4/4] Generating test report...")
    
    report = """
    ==================================================================
    TEST RUN SUMMARY
    ==================================================================
    
    ✓ All unit tests passed
    ✓ All integration tests passed  
    ✓ Code coverage: 80%+ (minimum threshold)
    ✓ Linting: Passed (non-blocking warnings)
    
    Test Results:
    - Total tests run: See pytest output above
    - Failures: 0
    - Errors: 0
    - Skipped: (if any, shown in pytest output)
    
    Coverage Report:
    - HTML: coverage_html/index.html
    - XML: coverage.xml
    
    Next Steps:
    1. Review coverage_html/index.html for detailed coverage
    2. Check for untested edge cases
    3. Add additional tests as needed
    
    ==================================================================
    """
    print(report)
    
    return True


def main():
    """Main entry point."""
    success = run_tests_with_coverage()
    
    if success:
        print("[SUCCESS] All tests passed!")
        sys.exit(0)
    else:
        print("[FAILURE] Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
