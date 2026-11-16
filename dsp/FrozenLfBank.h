#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <iterator>

namespace altair::lf {
namespace data {
#include "FrozenLfData.inc"
}

class FrozenLfBank {
    using Weights = std::array<double,203>;
    struct Rate {
        int taps, post, extra;
        const double *pr,*pi,*norm,*fir,*tail,*table,*local,*edge;
    };
    struct Channel {
        std::array<double,105> input{};
        std::array<double,49> re{}, im{};
        std::array<double,32> filtered{};
    };
    struct Ramp {
        double value=1, target=1, step=0;
        int left=0;
        void set(double v,int n) {
            if(v==target) return;
            target=v; step=(v-value)/n; left=n;
        }
        void advance() {
            if(left) {value+=step; if(--left==0) value=target;}
        }
    };
    Rate rate{};
    int duration=0, remaining=0, inputPos=0, postPos=0;
    Channel channels[2]{};
    Weights current{},target{},step{};
    Ramp wet{},trim{};

    static double cubic(double x,int j,int start) {
        double v=1;
        for(int k=start;k<start+4;++k) if(k!=j) v*= (x-k)/(j-k);
        return v;
    }
    static double hat(double x,int i,const double (&grid)[4]) {
        x=std::clamp(x,grid[0],grid[3]);
        if(x==grid[i]) return 1;
        if(i && x<grid[i] && x>grid[i-1]) return (x-grid[i-1])/(grid[i]-grid[i-1]);
        if(i<3 && x>grid[i] && x<grid[i+1]) return (grid[i+1]-x)/(grid[i+1]-grid[i]);
        return 0;
    }
    double sample(double x,Channel& ch) {
        ch.input[inputPos]=x;
        double sum=0, extra=0;
        int j=inputPos;
        for(int k=0;k<std::max(rate.taps,rate.extra);++k) {
            if(k<rate.taps) sum+=current[k]*ch.input[j];
            if(k<rate.extra) extra+=rate.tail[k]*ch.input[j];
            if(--j<0) j=104;
        }
        for(int k=0;k<49;++k) {
            double r=rate.pr[k]*ch.re[k]-rate.pi[k]*ch.im[k]+rate.norm[k]*x;
            ch.im[k]=rate.pi[k]*ch.re[k]+rate.pr[k]*ch.im[k];
            ch.re[k]=r;
            sum+=current[rate.taps+k]*r+current[rate.taps+49+k]*ch.im[k];
        }
        ch.filtered[postPos]=sum;
        j=postPos;
        for(int k=0;k<rate.post;++k) {
            extra+=rate.fir[k]*ch.filtered[j];
            if(--j<0) j=31;
        }
        return (x+wet.value*(extra-x))*trim.value;
    }
public:
    bool prepare(int sr) {
        using namespace data;
        Rate next{};
#define LF_RATE(s,t) {t, int(std::size(fir##s)), int(std::size(tail##s)), pr##s,pi##s,norm##s,fir##s,tail##s,table##s,local##s,edge##s}
        switch(sr) {
            case 44100: next=LF_RATE(44100,48); break;
            case 48000: next=LF_RATE(48000,53); break;
            case 96000: next=LF_RATE(96000,105); break;
            default: return false;
        }
#undef LF_RATE
        *this=FrozenLfBank{}; rate=next; duration=sr/50;
        setControls(30,0,0); current=target; remaining=0;
        return true;
    }
    bool setControls(int cps,double b,double a) {
        int i=cps==20?0:cps==30?1:cps==60?2:cps==100?3:-1;
        if(!duration || i<0 || !std::isfinite(b) || !std::isfinite(a) || b<0 || b>10 || a<0 || a>10) return false;
        const int width=rate.taps+98;
        Weights next{};
        auto add=[&](const double* values,double v) {
            if(v!=0) for(int k=0;k<width;++k) next[k]+=v*values[k];
        };
        int bs=std::clamp(int(b)-1,0,7), as=std::clamp(int(a)-1,0,7);
        for(int j=bs;j<bs+4;++j) for(int k=as;k<as+4;++k)
            add(rate.table+((i*11+j)*11+k)*width,cubic(b,j,bs)*cubic(a,k,as));
        constexpr double bg[]={0,1.25,2.25,3.25}, ag[]={6,7,9,10};
        for(int j=0;j<4;++j) for(int k=0;k<4;++k)
            add(rate.local+((i*4+j)*4+k)*width,hat(b,j,bg)*hat(a,k,ag));
        constexpr int centers=int(std::size(data::centers))/2;
        for(int j=0;j<centers;++j) {
            double r=std::hypot(b-data::centers[2*j],a-data::centers[2*j+1])/1.75;
            if(r<1) {
                double t=(1-r)*(1-r);
                add(rate.edge+(i*centers+j)*width,t*t*(1+4*r)*std::min(b,1.)*std::min(a,1.));
            }
        }
        if(next!=target) {
            target=next; remaining=duration;
            for(int k=0;k<width;++k) step[k]=(target[k]-current[k])/duration;
        }
        return true;
    }
    void setEnabled(bool on) { if(duration) wet.set(on?1:0,duration); }
    void setTrimDb(double db) {
        if(duration && std::isfinite(db)) trim.set(std::pow(10.,std::clamp(db,-12.,12.)/20),duration);
    }
    void process(double& left,double& right,bool hostBypass=false) {
        if(!duration) return;
        if(remaining) {
            if(--remaining==0) current=target;
            else for(int k=0;k<rate.taps+98;++k) current[k]+=step[k];
        }
        wet.advance(); trim.advance();
        double l=sample(left,channels[0]), r=sample(right,channels[1]);
        if(!hostBypass) {left=l;right=r;}
        inputPos=(inputPos+1)%105; postPos=(postPos+1)%32;
    }
    double processMono(double input,bool hostBypass=false) {
        double unused=0; process(input,unused,hostBypass); return input;
    }
};
}
