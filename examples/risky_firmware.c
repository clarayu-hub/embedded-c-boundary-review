/*
 * risky_firmware.c — 刻意植入缺陷的示例文件（请勿用于生产代码）
 *
 * 用途：演示 13 项边界风险的典型写法，并作为扫描器回归测试的输入。
 * 每个缺陷所在行都有 `[R?]` 标记，对照表见 examples/README.md。
 *
 * 声明：本文件是反面教材。每一处写法在这里都是「坏的」，
 *      复制粘贴到项目里会引入真实缺陷。
 */

#include <stdint.h>
#include <string.h>
#include <time.h>

/* [R13] 常量来源见 examples/README.md */
#define TMR_EXPIRE_GUARD_MS 900
#define MAX_PERIOD_MS 3600000
#define RING_SIZE 16
#define CFG_MAGIC 0xA5A5

static uint32_t sys_now_ms;
static uint32_t last_report_ms;
static uint32_t last_seq;
static uint16_t pulse_total;
static int32_t  time_diff_ms;
static uint16_t day_count;
static time_t   last_valid_ts;
static uint8_t  head, tail;

struct pkt {
    const uint8_t *data;
    uint16_t len;
    uint32_t seq;
};

/* [R1] 回绕点之后条件永远不成立：定时器/上报彻底停摆 */
void tick_wrap_bad(void)
{
    if (sys_now_ms > last_report_ms + 300000) {
        last_report_ms = sys_now_ms;
    }
}

/* [R2] 有符号差值 + 有符号中间变量：越界时结果未定义 */
int32_t diff_signed(void)
{
    time_diff_ms = sys_now_ms - last_report_ms;
    return time_diff_ms;
}

/* [R3] 自定纪元的天计数：16 位日计数约 179 年后耗尽，且产品寿命内无校验 */
void day_counter(void)
{
    day_count++;
    if (day_count == 0) {
        /* 无处可查：耗尽后无任何处理分支 */
    }
}

/* [R4] 取到时间就直接用于有效期判断，没有「已同步 / 是否有效」前置检查 */
int is_cert_valid(void)
{
    time_t now = time(NULL);
    return (now < g_cert_expire_ts);
}

/* [R5] 定长累加器溢出语义未定义：脉冲总数在长期运行后静默回绕 */
void accum(uint16_t pulses)
{
    pulse_total += pulses;
    pulse_total++;
}

/* [R6] 「数值更大即更新」：序号回绕后新包被当成旧包丢弃 */
void parse_seq(const struct pkt *p)
{
    if (p->seq > last_seq) {
        last_seq = p->seq;
    }
}

/* [R7] 长度字段直接用于 memcpy：长度未与本地容量取小/校验 */
void parse_packet(const struct pkt *p)
{
    uint8_t dst[64];
    memcpy(dst, p->data, p->len);
}

/* [R8] head == tail 无法区分满与空，且未按环形语义推进 */
void ring_push(uint8_t v)
{
    if (head == tail) {
        return;
    }
    head = (uint8_t)((head + 1) % RING_SIZE);
    (void)v;
}

/* [R9] 无符号相减结果赋给有符号/收窄类型，比较语义会翻转 */
uint16_t remaining(uint16_t cap, uint16_t used)
{
    if (used > cap) {
        return 0;
    }
    {
        uint16_t remain = cap - used;
        int len = sizeof(remain);
        return (uint16_t)(remain + len);
    }
}

/* [R10] off-by-one：<= 循环 + strcpy 无长度约束 */
void copy_str(const char *name, uint8_t *out)
{
    char tmp[16];
    strcpy(tmp, name);
    for (int i = 0; i <= 16; i++) {
        out[i] = (uint8_t)tmp[i];
    }
}

/* [R11] 下行配置量程未与本地收窄类型核对，直接强转 uint8_t */
void apply_downlink(const struct cfg *c)
{
    uint8_t period = (uint8_t)c->period;
    uint8_t threshold = (uint8_t)c->threshold;
    (void)period;
    (void)threshold;
}

/* [R12] NVS 读回的初值在 magic 校验之前就被使用 */
void boot(void)
{
    nvs_read_config(&g_cfg, sizeof(g_cfg));
    use_config(&g_cfg);
    if (g_cfg.magic != CFG_MAGIC) {
        reset_cfg();
    }
}
