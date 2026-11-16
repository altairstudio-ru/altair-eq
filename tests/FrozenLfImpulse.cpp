#include "FrozenLfBank.h"
#include <fstream>
#include <iostream>

int main(int argc,char** argv) {
    if(argc!=2) return 1;
    std::ofstream output(argv[1],std::ios::binary);
    int sr,c; double b,a;
    while(std::cin>>sr>>c>>b>>a) {
        altair::lf::FrozenLfBank bank;
        if(!bank.prepare(sr) || !bank.setControls(c,b,a)) return 2;
        for(int k=0;k<sr/50;++k) bank.processMono(0);
        std::array<double,1024> block{};
        for(int j=0;j<128;++j) {
            for(int k=0;k<1024;++k) block[k]=bank.processMono(j==0 && k==0?1.:0.);
            output.write(reinterpret_cast<const char*>(block.data()),sizeof(block));
        }
    }
    return output && std::cin.eof()?0:3;
}
