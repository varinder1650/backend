#!/bin/bash

# SmartBag Test Runner Script
# Usage: ./run_tests.sh [options]

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     SmartBag Test Suite Runner        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if virtual environment exists
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    print_warning "No virtual environment found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    print_success "Virtual environment created and activated"
else
    # Activate existing venv
    if [ -d "venv" ]; then
        source venv/bin/activate
    else
        source .venv/bin/activate
    fi
    print_success "Virtual environment activated"
fi

# Install dependencies if needed
if ! pip show pytest > /dev/null 2>&1; then
    print_info "Installing test dependencies..."
    pip install -r requirements-test.txt
    print_success "Dependencies installed"
else
    print_success "Dependencies already installed"
fi

# Check if MongoDB is running
print_info "Checking MongoDB connection..."
if mongosh --eval "db.runCommand({ ping: 1 })" --quiet > /dev/null 2>&1; then
    print_success "MongoDB is running"
else
    print_error "MongoDB is not running!"
    print_info "Please start MongoDB: sudo systemctl start mongod"
    exit 1
fi

# Check if Redis is running
print_info "Checking Redis connection..."
if redis-cli ping > /dev/null 2>&1; then
    print_success "Redis is running"
else
    print_error "Redis is not running!"
    print_info "Please start Redis: sudo systemctl start redis"
    exit 1
fi

# Set test environment variables
export ENVIRONMENT=Testing
export TEST_MONGODB_URL=${TEST_MONGODB_URL:-"mongodb://localhost:27017/smartbag_test"}
export TEST_REDIS_URL=${TEST_REDIS_URL:-"redis://localhost:6379/1"}

print_info "Test environment configured"
echo ""

# Parse command line arguments
COVERAGE=false
PARALLEL=false
VERBOSE=false
HTML_REPORT=false
INTEGRATION=false
SPECIFIC_TEST=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        -p|--parallel)
            PARALLEL=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--html)
            HTML_REPORT=true
            shift
            ;;
        -i|--integration)
            INTEGRATION=true
            shift
            ;;
        -t|--test)
            SPECIFIC_TEST="$2"
            shift 2
            ;;
        --help)
            echo "Usage: ./run_tests.sh [options]"
            echo ""
            echo "Options:"
            echo "  -c, --coverage     Generate coverage report"
            echo "  -p, --parallel     Run tests in parallel"
            echo "  -v, --verbose      Verbose output"
            echo "  -h, --html         Generate HTML report"
            echo "  -i, --integration  Run integration tests"
            echo "  -t, --test <path>  Run specific test file or function"
            echo "  --help             Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./run_tests.sh                          # Run all tests"
            echo "  ./run_tests.sh -c -h                    # With coverage and HTML report"
            echo "  ./run_tests.sh -p                       # Parallel execution"
            echo "  ./run_tests.sh -t tests/test_auth.py   # Run specific file"
            echo "  ./run_tests.sh -i                       # Run integration tests"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest"

if [ ! -z "$SPECIFIC_TEST" ]; then
    PYTEST_CMD="$PYTEST_CMD $SPECIFIC_TEST"
fi

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -vv -s"
else
    PYTEST_CMD="$PYTEST_CMD -v"
fi

if [ "$PARALLEL" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -n auto"
    print_info "Running tests in parallel..."
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=app --cov-report=term --cov-report=html"
    print_info "Coverage report will be generated..."
fi

if [ "$HTML_REPORT" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --html=test-report.html --self-contained-html"
    print_info "HTML report will be generated..."
fi

if [ "$INTEGRATION" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -m integration"
    print_info "Running integration tests only..."
fi

# Clean up previous test artifacts
print_info "Cleaning up previous test data..."
mongosh smartbag_test --eval "db.dropDatabase()" --quiet > /dev/null 2>&1 || true
redis-cli -n 1 FLUSHDB > /dev/null 2>&1 || true
print_success "Test environment cleaned"

echo ""
print_info "Running tests..."
echo "Command: $PYTEST_CMD"
echo ""

# Run tests
if $PYTEST_CMD; then
    echo ""
    print_success "All tests passed! 🎉"
    
    # Show reports generated
    if [ "$COVERAGE" = true ]; then
        echo ""
        print_info "Coverage report available at: htmlcov/index.html"
    fi
    
    if [ "$HTML_REPORT" = true ]; then
        print_info "HTML test report available at: test-report.html"
    fi
    
    echo ""
    exit 0
else
    echo ""
    print_error "Some tests failed! 😞"
    print_info "Review the output above for details"
    
    # Suggest debugging commands
    echo ""
    print_info "Debugging suggestions:"
    echo "  • Run failed tests only: pytest --lf"
    echo "  • Run with debugger: pytest --pdb"
    echo "  • Run specific test: pytest tests/test_file.py::TestClass::test_method"
    
    echo ""
    exit 1
fi