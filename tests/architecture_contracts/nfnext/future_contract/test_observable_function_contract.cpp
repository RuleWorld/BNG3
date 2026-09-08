#include "contract_test.hpp"

#if __has_include("nfnext/observables.hpp") && __has_include("nfnext/function_vm.hpp")
#include "nfnext/observables.hpp"
#include "nfnext/function_vm.hpp"
#include "nfnext/generic_matcher.hpp"
#include <cmath>
using namespace nfnext;

CONTRACT_CASE("molecule observable sums independent pattern contributions") {
    auto f=makeObservableFixture();
    auto obs=MoleculeObservableIR("sum");
    obs.addPattern(f.patternAState0());
    obs.addPattern(f.patternAAny());
    f.state.setSiteState(f.a0,"x",0);
    // Same molecule matches both terms and contributes twice, matching legacy semantics.
    REQUIRE_EQ(compileObservable(obs,f.model).evaluate(f.state),2.0);
}

CONTRACT_CASE("species observable counts matching complexes once per pattern") {
    auto f=makeObservableFixture(); f.state.bind(f.a0,"b",f.b0,"a");
    SpeciesObservableIR obs("AB"); obs.addPattern(f.patternABComplex());
    REQUIRE_EQ(compileObservable(obs,f.model).evaluate(f.state),1.0);
}

CONTRACT_CASE("species observable does not count each molecule in matching complex") {
    auto f=makeObservableFixture(); f.state.bind(f.a0,"b",f.b0,"a");
    SpeciesObservableIR obs("AB"); obs.addPattern(f.patternABComplex());
    REQUIRE_EQ(compileObservable(obs,f.model).evaluate(f.state),1.0);
}

CONTRACT_CASE("stoichiometric complex observable equality constraint is exact") {
    auto f=makeObservableFixture(); auto a1=f.state.create(f.A); f.state.bind(f.a0,"b",f.b0,"a");
    SpeciesObservableIR obs("twoA"); auto term=f.patternAAny(); term.stoichiometry=StoichConstraint::equal(2); obs.addPattern(term);
    REQUIRE_EQ(compileObservable(obs,f.model).evaluate(f.state),0.0);
    f.state.bind(a1,"b",f.state.create(f.B),"a");
    REQUIRE_EQ(compileObservable(obs,f.model).evaluate(f.state),0.0); // two separate complexes each have one A
}

CONTRACT_CASE("all stoichiometric comparison operators are supported") {
    for(auto op: {StoichOp::Eq,StoichOp::Ne,StoichOp::Gt,StoichOp::Lt,StoichOp::Ge,StoichOp::Le}) {
        REQUIRE_NO_THROW(StoichConstraint{op,2}.validate());
    }
}

CONTRACT_CASE("incremental observable update equals full recomputation after state change") {
    auto f=makeObservableFixture(); MoleculeObservableIR obs("p"); obs.addPattern(f.patternAState1()); auto c=compileObservable(obs,f.model); ObservableRuntime r(c,f.state);
    for(int i=0;i<100;++i){auto p=f.state.create(f.A); f.state.setSiteState(p,"x",i&1); r.apply(f.state.takeMutations()); REQUIRE_EQ(r.value(),c.evaluate(f.state));}
}

CONTRACT_CASE("incremental observable update equals full recomputation after bind and unbind") {
    auto f=makeObservableFixture(); MoleculeObservableIR obs("freeA"); obs.addPattern(f.patternAFree()); auto c=compileObservable(obs,f.model); ObservableRuntime r(c,f.state);
    f.state.bind(f.a0,"b",f.b0,"a"); r.apply(f.state.takeMutations()); REQUIRE_EQ(r.value(),c.evaluate(f.state));
    f.state.unbind(f.a0,"b"); r.apply(f.state.takeMutations()); REQUIRE_EQ(r.value(),c.evaluate(f.state));
}

CONTRACT_CASE("incremental species observable handles complex merge and split") {
    auto f=makeObservableFixture(); SpeciesObservableIR obs("complexA"); obs.addPattern(f.patternAAny()); auto c=compileObservable(obs,f.model); ObservableRuntime r(c,f.state);
    f.state.bind(f.a0,"b",f.b0,"a"); r.apply(f.state.takeMutations()); REQUIRE_EQ(r.value(),c.evaluate(f.state));
    f.state.unbind(f.a0,"b"); r.apply(f.state.takeMutations()); REQUIRE_EQ(r.value(),c.evaluate(f.state));
}

CONTRACT_CASE("observable update touches only dependency-indexed observables") {
    auto f=makeObservableFixture(); auto set=makeLargeObservableSet(f.model,10000); ObservableBank bank(set,f.state); auto before=bank.updateCounter(); f.state.setSiteState(f.a0,"x",1); bank.apply(f.state.takeMutations()); REQUIRE(bank.updateCounter()-before < 64u);
}

CONTRACT_CASE("constant function compiles to zero-dependency bytecode") {
    FunctionCompiler fc; auto fn=fc.compile("2.5 + 4*3",FunctionEnvironment{}); REQUIRE(fn.dependencies().empty()); REQUIRE_NEAR(fn.evaluate({}),14.5,1e-12);
}

CONTRACT_CASE("parameter function records exact parameter dependency") {
    FunctionEnvironment e; e.addParameter("k",2.0,7); auto fn=FunctionCompiler().compile("k*3",e); REQUIRE_EQ(fn.parameterDependencies(),std::vector<ParameterId>({7})); REQUIRE_NEAR(fn.evaluate(e),6.0,1e-12);
}

CONTRACT_CASE("observable-dependent function records exact observable dependency") {
    FunctionEnvironment e; e.addObservable("Obs",5.0,9); auto fn=FunctionCompiler().compile("1+Obs*2",e); REQUIRE_EQ(fn.observableDependencies(),std::vector<ObservableId>({9})); REQUIRE_NEAR(fn.evaluate(e),11.0,1e-12);
}

CONTRACT_CASE("function evaluation obeys operator precedence and parentheses") {
    FunctionEnvironment e; FunctionCompiler fc; REQUIRE_NEAR(fc.compile("2+3*4",e).evaluate(e),14,0); REQUIRE_NEAR(fc.compile("(2+3)*4",e).evaluate(e),20,0);
}

CONTRACT_CASE("function supports legacy elementary math functions") {
    FunctionEnvironment e; auto fn=FunctionCompiler().compile("exp(log(5))+sqrt(9)+pow(2,3)",e); REQUIRE_NEAR(fn.evaluate(e),16.0,1e-12);
}

CONTRACT_CASE("function rejects unknown symbol at compile time") {
    REQUIRE_THROWS_AS(FunctionCompiler().compile("k_missing+1",FunctionEnvironment{}),FunctionCompileError);
}

CONTRACT_CASE("function rejects division by zero according to explicit runtime policy") {
    FunctionCompilerOptions o; o.nonfinite_policy=NonFinitePolicy::Reject; auto fn=FunctionCompiler(o).compile("1/x",FunctionEnvironment::parameter("x",0)); REQUIRE_THROWS_AS(fn.evaluate(FunctionEnvironment::parameter("x",0)),FunctionEvaluationError);
}

CONTRACT_CASE("function rate negative result is rejected before scheduler update") {
    FunctionEnvironment e=FunctionEnvironment::parameter("x",-1); auto fn=FunctionCompiler().compile("x",e); REQUIRE_THROWS_AS(validatePropensity(fn.evaluate(e)),InvalidPropensity);
}

CONTRACT_CASE("function NaN and infinity never enter scheduler") {
    for(double x:{std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()}) REQUIRE_THROWS_AS(validatePropensity(x),InvalidPropensity);
}

CONTRACT_CASE("local function can be evaluated on matched complex scope") {
    auto f=makeObservableFixture(); LocalFunctionIR lf("nA","count(A)"); auto c=compileLocalFunction(lf,f.model); f.state.bind(f.a0,"b",f.b0,"a"); REQUIRE_EQ(c.evaluateOnComplex(f.state,f.a0),1.0);
}

CONTRACT_CASE("local function scope never leaks to other complexes") {
    auto f=makeObservableFixture(); auto another=f.state.create(f.A); LocalFunctionIR lf("nA","count(A)"); auto c=compileLocalFunction(lf,f.model); REQUIRE_EQ(c.evaluateOnComplex(f.state,f.a0),1.0); REQUIRE_EQ(c.evaluateOnComplex(f.state,another),1.0);
}

CONTRACT_CASE("compiled function bytecode is immutable and shareable") {
    FunctionEnvironment e=FunctionEnvironment::parameter("k",1); auto fn=FunctionCompiler().compile("k+1",e); REQUIRE(fn.isImmutable()); auto copy=fn.sharedCode(); REQUIRE_EQ(copy.get(),fn.sharedCode().get());
}

CONTRACT_CASE("function VM performs no dynamic allocation during repeated evaluation") {
    FunctionEnvironment e=FunctionEnvironment::parameter("k",1); auto fn=FunctionCompiler().compile("sin(k)+k*k",e); auto before=allocationCounter(); for(int i=0;i<100000;++i){e.set("k",i*.001);(void)fn.evaluate(e);} REQUIRE_EQ(allocationCounter(),before);
}

CONTRACT_MAIN("observable-function")
#else
#error "RED CONTRACT: implement compiled observables and function VM"
#endif
