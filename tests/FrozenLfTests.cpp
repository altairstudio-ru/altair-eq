#include "FrozenLfBank.h"
#include "FrozenLfVectors.inc"
#include <iostream>

bool run(int sr,const double* golden) {
    altair::lf::FrozenLfBank bank,mono;
    if(!bank.prepare(sr) || !mono.prepare(sr)) return false;
    const int n=sr/50;
    double maximum=0;
    for(int k=0;k<5*n;++k) {
        if(k==n || k==n+n/2) {
            for(auto* processor:{&bank,&mono})
                if(!processor->setControls(k==n?60:100,k==n?.5:4.5,k==n?10:4.5)) return false;
        }
        double t=double(k)/sr;
        double x=.06*std::sin(2*3.141592653589793*53*t)+.01*std::cos(2*3.141592653589793*1300*t);
        double l=x,r=0;
        bank.process(l,r);
        if(r!=0 || mono.processMono(x)!=l || !std::isfinite(l)) return false;
        if(k%13==0) maximum=std::max(maximum,std::abs(l-golden[k/13]));
    }
    bank.setEnabled(false);
    bank.setTrimDb(-6);
    for(int k=0;k<=n;++k) {
        double l=.125,r=-.25; bank.process(l,r);
        if(k==n && (std::abs(l-.125*std::pow(10.,-.3))>1e-12 ||
                     std::abs(r+.25*std::pow(10.,-.3))>1e-12)) return false;
    }
    double l=.125,r=-.25; bank.process(l,r,true);
    std::cout<<sr<<" max difference "<<maximum<<"\n";
    return l==.125 && r==-.25 && maximum<1e-8;
}
int main() {
    return run(44100,gold44100)&&run(48000,gold48000)&&run(96000,gold96000)?0:1;
}
