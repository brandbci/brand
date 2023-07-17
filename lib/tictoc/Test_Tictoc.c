#include "Tictoc.h"
#include <stdio.h>
#include <unistd.h>

int main()
{
	struct timespec tStart = Tic();

	usleep(1000);
	
	struct timespec tEnd = Toc(&tStart);
	PrintToc(&tEnd);
	
	return 0;
}

