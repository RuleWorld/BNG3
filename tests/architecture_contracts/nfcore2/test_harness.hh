#pragma once
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace nf2test {

struct Failure : public std::runtime_error {
    explicit Failure(const std::string& s) : std::runtime_error(s) {}
};

struct Case { const char* name; void (*fn)(); Case(const char* n, void(*f)()):name(n),fn(f){} };
inline std::vector<Case>& registry(){ static std::vector<Case> r; return r; }
struct Registrar { Registrar(const char* n, void(*f)()){ registry().push_back(Case(n,f)); } };

inline void fail(const char* file,int line,const std::string& msg){
    std::ostringstream os; os << file << ':' << line << ": " << msg; throw Failure(os.str());
}

template<class A,class B> inline void expectEq(const A&a,const B&b,const char* ea,const char* eb,const char* file,int line){
    if(!(a==b)){ std::ostringstream os; os << "expected "<<ea<<" == "<<eb; fail(file,line,os.str()); }
}
template<class A,class B> inline void expectNe(const A&a,const B&b,const char* ea,const char* eb,const char* file,int line){
    if(a==b){ std::ostringstream os; os << "expected "<<ea<<" != "<<eb; fail(file,line,os.str()); }
}
inline void expectNear(double a,double b,double tol,const char* file,int line){
    if(!(std::fabs(a-b)<=tol)){ std::ostringstream os; os<<"expected "<<a<<" ~= "<<b<<" +/- "<<tol; fail(file,line,os.str()); }
}

template<class E,class F> inline void expectThrows(F f,const char* expr,const char* file,int line){
    try { f(); }
    catch(const E&) { return; }
    catch(const std::exception& e){ std::ostringstream os; os<<"expected exception for "<<expr<<", got different std::exception: "<<e.what(); fail(file,line,os.str()); }
    catch(...){ fail(file,line,std::string("expected exception for ")+expr+", got non-std exception"); }
    fail(file,line,std::string("expected exception for ")+expr+", but nothing was thrown");
}

inline int runAll(){
    int failed=0; std::size_t passed=0;
    for(std::size_t i=0;i<registry().size();++i){
        try { registry()[i].fn(); ++passed; }
        catch(const std::exception& e){ ++failed; std::cerr << "FAIL "<<registry()[i].name<<" -- "<<e.what()<<'\n'; }
        catch(...){ ++failed; std::cerr << "FAIL "<<registry()[i].name<<" -- unknown exception\n"; }
    }
    std::cout << "NFcore2 tests: "<<passed<<" passed, "<<failed<<" failed, "<<registry().size()<<" total\n";
    return failed?1:0;
}

} // namespace nf2test

#define NF2_JOIN2(a,b) a##b
#define NF2_JOIN(a,b) NF2_JOIN2(a,b)
#define TEST(name) static void name(); static nf2test::Registrar NF2_JOIN(reg_,__LINE__)(#name,&name); static void name()
#define EXPECT_TRUE(x) do{ if(!(x)) nf2test::fail(__FILE__,__LINE__,std::string("expected true: ")+#x); }while(0)
#define EXPECT_FALSE(x) do{ if((x)) nf2test::fail(__FILE__,__LINE__,std::string("expected false: ")+#x); }while(0)
#define EXPECT_EQ(a,b) nf2test::expectEq((a),(b),#a,#b,__FILE__,__LINE__)
#define EXPECT_NE(a,b) nf2test::expectNe((a),(b),#a,#b,__FILE__,__LINE__)
#define EXPECT_NEAR(a,b,t) nf2test::expectNear((a),(b),(t),__FILE__,__LINE__)
#define EXPECT_THROW(expr,Exc) nf2test::expectThrows<Exc>([&](){ (void)(expr); },#expr,__FILE__,__LINE__)
#define EXPECT_NO_THROW(expr) do{ try{ (void)(expr); }catch(const std::exception&e){ nf2test::fail(__FILE__,__LINE__,std::string("unexpected exception: ")+e.what()); } }while(0)
